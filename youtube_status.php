<?php
/**
 * YouTube Live Stream Status Checker
 * Returns JSON: {"status": "live|offline", "title": "...", "viewers": 123}
 * 
 * SETUP:
 * 1. Place this file in your nginx web root
 * 2. Create a config file at a SECURE location (outside web root!)
 * 3. Update CONFIG_PATH below to point to your config file
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

// IMPORTANT: Store this file OUTSIDE your web root for security!
// Example: /etc/vantagecam/youtube_config.php
define('CONFIG_PATH', '/config/etc/vantagecam/youtube_config.php');

// Cache settings (avoid hammering YouTube API - you get 10,000 quota units/day)
define('CACHE_FILE', '/tmp/youtube_status_cache.json');
define('CACHE_TTL', 60); // seconds - check YouTube every 60 seconds max

// ============================================================================
// CORS HEADERS (adjust allowed origins as needed)
// ============================================================================

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *'); // Or restrict to your domain
header('Access-Control-Allow-Methods: GET');
header('Cache-Control: public, max-age=30');

// ============================================================================
// MAIN LOGIC
// ============================================================================

// Load config
if (!file_exists(CONFIG_PATH)) {
    http_response_code(500);
    echo json_encode(['error' => 'Config file not found', 'status' => 'unknown']);
    exit;
}

require_once CONFIG_PATH;

// Check required config constants
if (!defined('YOUTUBE_CLIENT_ID') || !defined('YOUTUBE_CLIENT_SECRET') || !defined('YOUTUBE_REFRESH_TOKEN')) {
    http_response_code(500);
    echo json_encode(['error' => 'Missing OAuth credentials in config', 'status' => 'unknown']);
    exit;
}

// Check cache first
if (file_exists(CACHE_FILE)) {
    $cache = json_decode(file_get_contents(CACHE_FILE), true);
    if ($cache && isset($cache['timestamp']) && (time() - $cache['timestamp']) < CACHE_TTL) {
        echo json_encode($cache['data']);
        exit;
    }
}

// Get fresh access token using refresh token
$accessToken = getAccessToken();
if (!$accessToken) {
    $result = ['status' => 'error', 'message' => 'Failed to get access token'];
    cacheResult($result);
    echo json_encode($result);
    exit;
}

// Query YouTube for live broadcasts
$status = checkLiveStatus($accessToken);
cacheResult($status);
echo json_encode($status);

// ============================================================================
// FUNCTIONS
// ============================================================================

function getAccessToken() {
    $tokenUrl = 'https://oauth2.googleapis.com/token';
    
    $postData = [
        'client_id' => YOUTUBE_CLIENT_ID,
        'client_secret' => YOUTUBE_CLIENT_SECRET,
        'refresh_token' => YOUTUBE_REFRESH_TOKEN,
        'grant_type' => 'refresh_token'
    ];
    
    $ch = curl_init();
    curl_setopt_array($ch, [
        CURLOPT_URL => $tokenUrl,
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => http_build_query($postData),
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 10
    ]);
    
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    
    if ($httpCode !== 200) {
        error_log("YouTube OAuth token refresh failed: " . $response);
        return null;
    }
    
    $data = json_decode($response, true);
    return $data['access_token'] ?? null;
}

function checkLiveStatus($accessToken) {
    // Check for active live broadcasts
    $apiUrl = 'https://www.googleapis.com/youtube/v3/liveBroadcasts?' . http_build_query([
        'part' => 'snippet,status,statistics',
        'broadcastStatus' => 'active',  // Only get currently live broadcasts
        'broadcastType' => 'all'
    ]);
    
    $ch = curl_init();
    curl_setopt_array($ch, [
        CURLOPT_URL => $apiUrl,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 10,
        CURLOPT_HTTPHEADER => [
            'Authorization: Bearer ' . $accessToken
        ]
    ]);
    
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    
    if ($httpCode !== 200) {
        error_log("YouTube API request failed: " . $response);
        return ['status' => 'error', 'message' => 'API request failed'];
    }
    
    $data = json_decode($response, true);
    
    // Check if any broadcasts are live
    if (!empty($data['items'])) {
        $broadcast = $data['items'][0]; // Get first active broadcast
        
        return [
            'status' => 'live',
            'title' => $broadcast['snippet']['title'] ?? 'Live Stream',
            'viewers' => (int)($broadcast['statistics']['concurrentViewers'] ?? 0),
            'started' => $broadcast['snippet']['actualStartTime'] ?? null,
            'thumbnail' => $broadcast['snippet']['thumbnails']['medium']['url'] ?? null
        ];
    }
    
    return [
        'status' => 'offline',
        'title' => null,
        'viewers' => 0
    ];
}

function cacheResult($data) {
    $cache = [
        'timestamp' => time(),
        'data' => $data
    ];
    file_put_contents(CACHE_FILE, json_encode($cache));
}
