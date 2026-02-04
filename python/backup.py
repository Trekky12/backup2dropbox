import os
import sys
import json
from pathlib import Path
import subprocess
import shutil
from datetime import datetime
import dropbox

cfg_type = ""
if len(sys.argv) > 1:
    cfg_type = sys.argv[1] + "."

config_file = Path(__file__).parent / f"config.{cfg_type}json"

with open(config_file, "r") as f:
    settings = json.load(f)

folder = settings["folder"]
if settings.get("folder"):
    os.makedirs(folder, exist_ok=True)

files = []

# ----------------------------
# Create SQL Backup and zip
# ----------------------------
db = settings.get("database")
if db and db.get("type") in ("mysql", "sqlite"):
    if db["type"] == "mysql":
        sql_file = os.path.join(folder, "database.sql")
        cmd = ["mysqldump", "-h", db["host"], "-u", db["user"], f"--password={db['password']}", db["database"]]
    else:
        sql_file = os.path.join(folder, "database.db")
        cmd = ["sqlite3", "-cmd", "PRAGMA busy_timeout=10000", db["database"], f".backup {sql_file}"]

    if settings.get("docker", {}).get("container_name"):
        cmd = ["docker", "exec", settings["docker"]["container_name"]] + cmd

    try:
        with open(sql_file, "w") as f:
            subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, check=True)
        files.append(sql_file)
    except subprocess.CalledProcessError as e:
        print("Failed to create Backup:", e.stderr.decode(), file=sys.stderr)

# ----------------------------
# Create other files zip
# ----------------------------
if settings.get("files"):
    files_zip = os.path.join(folder, "files.zip")
    try:
        subprocess.run(["zip", "-r", files_zip, *settings["files"]], check=True)
        files.append(files_zip)
    except subprocess.CalledProcessError as e:
        print("Failed to create ZIP of folders:", e, file=sys.stderr)

# ----------------------------
# Create archive of all files
# ----------------------------
if files:
    prefix = settings["prefix"]
    suffix = settings["suffix"]
    timestamp = datetime.now().strftime("%Y_%m_%d_%H-%M-%S")

    use_7z = shutil.which("7z") is not None
    ext = ".7z" if use_7z else ".zip"

    archive_name = f"{prefix}{timestamp}{suffix}{ext}"
    archive_path = os.path.join(folder, archive_name)

    try:
        if use_7z:
            cmd = ["7z", "a", *settings["zip_params"], f"-p{settings['zip_password']}", "-mhe", "-r", "-spf2", archive_path, *files]
        else:
            cmd = ["zip", *settings["zip_params"], "-P", settings["zip_password"], archive_path, *files]

        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print("Failed to create complete archive:", e, file=sys.stderr)

    # -----------------------
    # Upload archive
    # -----------------------
    try:
        dbx = dropbox.Dropbox(settings["dropbox"]["access_token"])

        usage = dbx.users_get_space_usage()
        allocation = 0
        if usage.allocation.is_individual():
            allocation = usage.allocation.get_individual().allocated
        elif usage.allocation.is_team():
            allocation = usage.allocation.get_team().allocated

        if usage.used > allocation:
            raise Exception("Insufficient space!")

        file_size = os.path.getsize(archive_path)
        chunk_size = 8 * 1024 * 1024

        with open(archive_path, "rb") as f:
            if file_size <= chunk_size:
                dbx.files_upload(f.read(), "/" + archive_name, mode=dropbox.files.WriteMode.add, autorename=True)
            else:
                upload_session_start_result = dbx.files_upload_session_start(f.read(chunk_size))
                cursor = dropbox.files.UploadSessionCursor(session_id=upload_session_start_result.session_id, offset=f.tell())
                commit = dropbox.files.CommitInfo(path="/" + archive_name, mode=dropbox.files.WriteMode.add, autorename=True)

                while f.tell() < file_size:
                    remaining = file_size - f.tell()
                    data = f.read(min(chunk_size, remaining))
                    if remaining <= chunk_size:
                        dbx.files_upload_session_finish(data, cursor, commit)
                    else:
                        dbx.files_upload_session_append_v2(data, cursor)
                        cursor.offset = f.tell()
    except Exception as e:
        print("Upload to dropbox failed:", e, file=sys.stderr)

    # -----------------------
    # Cleanup
    # -----------------------
    try:
        os.remove(archive_path)
        for f in files:
            os.remove(f)
    except OSError as e:
        print("Failed to remove files:", e, file=sys.stderr)

sys.exit(0)
