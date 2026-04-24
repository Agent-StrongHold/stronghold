<?php
/**
 * Classic fallback — page.
 *
 * @package PhosphorNoir
 */
get_header(); ?>

<?php while ( have_posts() ) : the_post(); ?>
  <article <?php post_class( 'pn-single' ); ?>>
    <div class="pn-classification">[ <?php the_title(); ?> ]</div>
    <h1><?php the_title(); ?></h1>
    <div class="pn-content"><?php the_content(); ?></div>
  </article>
<?php endwhile; ?>

<?php get_footer(); ?>
