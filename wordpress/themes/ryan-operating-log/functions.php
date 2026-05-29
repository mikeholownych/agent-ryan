<?php
/**
 * Ryan Operating Log theme setup.
 */

if (! defined('ABSPATH')) {
    exit;
}

add_action('wp_enqueue_scripts', function (): void {
    $theme = wp_get_theme();

    wp_enqueue_style(
        'ryan-operating-log-style',
        get_stylesheet_uri(),
        [],
        $theme->get('Version')
    );
});
