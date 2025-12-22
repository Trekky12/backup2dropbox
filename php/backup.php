<?php

require __DIR__ . '/vendor/autoload.php';

use Kunnu\Dropbox\Dropbox;
use Kunnu\Dropbox\DropboxApp;
use Kunnu\Dropbox\DropboxFile;
use Kunnu\Dropbox\Exceptions\DropboxClientException;

date_default_timezone_set('Europe/Berlin');

$type = '';
if (defined('STDIN') && count($argv) > 1) {
    $type = $argv[1] . '.';
}
$settings = require 'config.' . $type . 'php';

$folder = $settings['folder'];

$files = [];
/**
 * Create SQL Backup and zip
 */
if (array_key_exists('database', $settings) && array_key_exists('type', $settings['database']) && in_array($settings['database']['type'], ['mysql', 'sqlite'])) {
    $fileSQLName = $folder . "database". ($settings['database']['type'] == 'sqlite' ? '.db' : '.sql');

    if ($settings['database']['type'] == 'mysql') {
        $createSQLBackup = "mysqldump -h " . $settings['database']['host'] . " -u " . $settings['database']['user'] . " --password='" . $settings['database']['password'] . "' " . $settings['database']['database'] . " > " . $fileSQLName . " 2>&1";
    } else if ($settings['database']['type'] == 'sqlite') {
        $createSQLBackup = "sqlite3 " . $settings['database']['database'] . " '.backup " . $fileSQLName . "' 2>&1";
    }

    // Docker
    if (array_key_exists('docker', $settings) && array_key_exists('container_name', $settings['docker']) && !empty($settings['docker']['container_name'])) {
        $createSQLBackup = "docker exec " . $settings['docker']['container_name'] . " " . $createSQLBackup;
    }

    try {
        // Create backup
        exec($createSQLBackup);

        $files[] = $fileSQLName;
    } catch (Exception $e) {
        echo "Failed to create Backup: " . $e->getMessage() . "\n";
    }
}

/**
 * Create other files zip
 */
if (array_key_exists('files', $settings) && !empty($settings['files'])) {
    $fileZipOtherFilesPath = $folder . "files.zip";

    $createZipOtherFiles = "zip -r $fileZipOtherFilesPath " . implode(" ", $settings['files']);

    try {
        // Create archive
        system($createZipOtherFiles);

        $files[] = $fileZipOtherFilesPath;
    } catch (Exception $e) {
        echo "Failed to create ZIP of folders: " . $e->getMessage() . "\n";
    }
}


/**
 * Create archive of all files
 */
if (count($files) > 0) {
    $prefix = $settings['prefix'];
    $suffix = $settings['suffix'];

    $fileExtension = ".zip";
    if (`which 7z`) {
        $fileExtension = ".7z";
    }

    $fileZipName = $prefix . date('Y_m_d_H-i-s') . $suffix . $fileExtension;
    $fileZipPath = $folder . $fileZipName;

    if (`which 7z`) {
        $createZipBackup = "7z a -t7z -p" . $settings['zip_password'] . " -mhe -r -spf2 $fileZipPath " . implode(" ", $files);
    } else {
        $createZipBackup = "zip -P " . $settings['zip_password'] . " $fileZipPath " . implode(" ", $files);
    }

    try {
        // Create archive
        system($createZipBackup);
    } catch (Exception $e) {
        echo "Failed to create complete archive: " . $e->getMessage() . "\n";
    }


    /**
     * Upload archive
     */
    try {
        $app = new DropboxApp($settings['dropbox']['client_id'], $settings['dropbox']['client_secret'], $settings['dropbox']['access_token']);
        $dropbox = new Dropbox($app);
        $fileZipDropbox = new DropboxFile($fileZipPath);
        $fileZipDropboxUploaded = $dropbox->upload($fileZipDropbox, "/" . $fileZipName, ['autorename' => true]);

        //echo $fileZipSQLDropboxUploaded->getPathDisplay();
    } catch (DropboxClientException $e) {
        echo $e->getMessage();
    }


    /**
     * Delete the temporary files
     */
    try {
        unset($fileZipDropbox);
    } catch (Exception $e) {
        echo "Failed to unset Dropbox file: " . $e->getMessage() . "\n";
    }

    try {
        unlink($fileZipPath);
        foreach ($files as $file) {
            unlink($file);
        }
    } catch (Exception $e) {
        echo "Failed to unlink files: " . $e->getMessage() . "\n";
    }
}
