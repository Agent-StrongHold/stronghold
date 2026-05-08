<?php
/**
 * Classic fallback — single post.
 *
 * @package PhosphorNoir
 */
get_header(); ?>

<?php while ( have_posts() ) : the_post(); ?>
  <article <?php post_class( 'pn-single' ); ?>>
    <a class="pn-back" href="<?php echo esc_url( home_url( '/' ) ); ?>">← ALL DISPATCHES</a>
    <div class="pn-post-meta" style="margin-top: 24px;">
      <span class="pn-date">◆ <?php echo esc_html( get_the_date( 'Y-m-d' ) ); ?></span>
      <span>/</span>
      <span><?php the_category( ', ' ); ?></span>
    </div>
    <h1><?php the_title(); ?></h1>
    <div class="pn-content">
      <?php the_content(); ?>
    </div>
    <hr class="pn-rule" />
    <div class="pn-byline">
      Posted by <strong>◆ <?php the_author(); ?></strong> · Warden-scanned egress · <?php echo esc_html( strlen( strip_tags( get_the_content() ) ) ); ?> bytes
    </div>
    <?php if ( comments_open() || get_comments_number() ) : ?>
      <div class="pn-comments"><?php comments_template(); ?></div>
    <?php endif; ?>
  </article>
<?php endwhile; ?>

<?php get_footer(); ?>
