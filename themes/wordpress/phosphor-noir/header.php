<?php
/**
 * @package PhosphorNoir
 */
?><!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
  <meta charset="<?php bloginfo( 'charset' ); ?>" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
<header class="pn-masthead">
  <div>
    <div class="pn-classification">[ A Field Dossier · Published Irregularly ]</div>
    <h1 class="pn-site-title"><a href="<?php echo esc_url( home_url( '/' ) ); ?>"><?php bloginfo( 'name' ); ?></a></h1>
    <div class="pn-site-description"><?php bloginfo( 'description' ); ?></div>
  </div>
  <nav class="pn-nav">
    <?php
      wp_nav_menu( array(
        'theme_location' => 'primary',
        'container'      => false,
        'items_wrap'     => '%3$s',
        'fallback_cb'    => function() {
          echo '<a href="' . esc_url( home_url( '/' ) ) . '">home</a>';
          echo '<a href="' . esc_url( home_url( '/about/' ) ) . '">about</a>';
        },
      ) );
    ?>
  </nav>
</header>
