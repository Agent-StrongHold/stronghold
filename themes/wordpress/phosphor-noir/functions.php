<?php
/**
 * Phosphor / Noir — theme bootstrap.
 *
 * @package PhosphorNoir
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

if ( ! function_exists( 'phosphor_noir_setup' ) ) :
    function phosphor_noir_setup() {
        add_theme_support( 'title-tag' );
        add_theme_support( 'post-thumbnails' );
        add_theme_support( 'responsive-embeds' );
        add_theme_support( 'editor-styles' );
        add_theme_support( 'wp-block-styles' );
        add_theme_support( 'html5', array( 'search-form', 'comment-form', 'comment-list', 'gallery', 'caption', 'style', 'script' ) );
        add_editor_style( 'style.css' );

        register_nav_menus( array(
            'primary' => __( 'Primary Nav', 'phosphor-noir' ),
        ) );
    }
endif;
add_action( 'after_setup_theme', 'phosphor_noir_setup' );

function phosphor_noir_assets() {
    wp_enqueue_style(
        'phosphor-noir-style',
        get_stylesheet_uri(),
        array(),
        wp_get_theme()->get( 'Version' )
    );
}
add_action( 'wp_enqueue_scripts', 'phosphor_noir_assets' );

/**
 * Body class — lets users opt into CRT scanlines with a body class.
 */
function phosphor_noir_body_class( $classes ) {
    $classes[] = 'phosphor-noir';
    if ( get_theme_mod( 'phosphor_noir_scanlines', false ) ) {
        $classes[] = 'pn-scanlines';
    }
    return $classes;
}
add_filter( 'body_class', 'phosphor_noir_body_class' );

/**
 * Excerpt — terse, noir, no "Read More …" ellipsis cruft.
 */
function phosphor_noir_excerpt_more( $more ) { return ' …'; }
add_filter( 'excerpt_more', 'phosphor_noir_excerpt_more' );
function phosphor_noir_excerpt_length( $n ) { return 36; }
add_filter( 'excerpt_length', 'phosphor_noir_excerpt_length' );

/**
 * Customizer — single option: scanlines overlay.
 */
function phosphor_noir_customize( $wp_customize ) {
    $wp_customize->add_setting( 'phosphor_noir_scanlines', array(
        'default'           => false,
        'sanitize_callback' => 'rest_sanitize_boolean',
    ) );
    $wp_customize->add_control( 'phosphor_noir_scanlines', array(
        'label'   => __( 'CRT scanlines overlay', 'phosphor-noir' ),
        'section' => 'colors',
        'type'    => 'checkbox',
    ) );
}
add_action( 'customize_register', 'phosphor_noir_customize' );
