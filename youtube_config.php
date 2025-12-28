<?php
/**
 * YouTube OAuth Configuration
 * 
 * SECURITY: This file must be stored OUTSIDE your web root!
 * Recommended location: /etc/vantagecam/youtube_config.php
 * 
 * Make sure nginx/php-fpm user can read it:
 *   sudo chown root:www-data /etc/vantagecam/youtube_config.php
 *   sudo chmod 640 /etc/vantagecam/youtube_config.php
 */



define('YOUTUBE_CLIENT_ID', 'YOURTOKENHERE');
define('YOUTUBE_CLIENT_SECRET', 'YOURSECRETHERE');
define('YOUTUBE_REFRESH_TOKEN', 'YOURREFRESHTOKENHERE');