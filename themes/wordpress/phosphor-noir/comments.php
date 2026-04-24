<?php
/**
 * @package PhosphorNoir
 */
if ( post_password_required() ) { return; }
?>
<div id="comments" class="pn-comments">
  <?php if ( have_comments() ) : ?>
    <h2>◆ Transmissions · <?php echo esc_html( get_comments_number() ); ?></h2>
    <ol class="commentlist" style="list-style:none; padding:0;">
      <?php wp_list_comments( array( 'style' => 'ol', 'short_ping' => true, 'avatar_size' => 0, 'callback' => 'phosphor_noir_comment' ) ); ?>
    </ol>
  <?php endif; ?>
  <?php comment_form( array(
    'title_reply'         => '◆ Transmit',
    'label_submit'        => 'TRANSMIT',
    'comment_notes_before'=> '',
    'comment_notes_after' => '',
  ) ); ?>
</div>
<?php
if ( ! function_exists( 'phosphor_noir_comment' ) ) {
  function phosphor_noir_comment( $comment, $args, $depth ) {
    $is_author = (int) $comment->user_id === (int) get_the_author_meta( 'ID' );
    $class = 'pn-comment' . ( $is_author ? ' pn-by-author' : '' );
    ?>
    <li <?php comment_class( $class ); ?>>
      <div class="pn-byline">◆ <?php echo esc_html( $comment->comment_author ); ?> · <?php echo esc_html( get_comment_date( 'Y-m-d H:i' ) ); ?></div>
      <div><?php comment_text(); ?></div>
    </li>
    <?php
  }
}
?>
