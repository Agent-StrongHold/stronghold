<?php
/**
 * Classic fallback — archive / home. FSE sites use templates/index.html.
 *
 * @package PhosphorNoir
 */
get_header(); ?>

<main class="pn-archive">
  <div>
    <div class="pn-section-label">◆ Dispatches</div>
    <?php if ( have_posts() ) : while ( have_posts() ) : the_post(); ?>
      <article <?php post_class( 'pn-post-card' ); ?>>
        <div class="pn-post-meta">
          <span class="pn-date">◆ <?php echo esc_html( get_the_date( 'Y-m-d' ) ); ?></span>
          <span>/</span>
          <span><?php the_category( ', ' ); ?></span>
        </div>
        <h2 class="pn-post-title">
          <a href="<?php the_permalink(); ?>"><?php the_title(); ?></a>
        </h2>
        <div class="pn-post-excerpt"><?php the_excerpt(); ?></div>
        <a class="pn-read-more" href="<?php the_permalink(); ?>">READ · →</a>
      </article>
    <?php endwhile; else : ?>
      <p>No signal. The wire is cold.</p>
    <?php endif; ?>

    <div class="pn-pagination">
      <?php the_posts_pagination(); ?>
    </div>
  </div>

  <aside class="pn-sidebar">
    <?php if ( is_active_sidebar( 'sidebar-1' ) ) dynamic_sidebar( 'sidebar-1' ); ?>
  </aside>
</main>

<?php get_footer(); ?>
