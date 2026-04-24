=== Phosphor / Noir ===
Contributors: AT-01
Tags: block-theme, full-site-editing, dark-mode, one-column
Requires at least: 6.4
Tested up to: 6.6
Requires PHP: 7.4
Stable tag: 1.0.0
License: GPLv2 or later

A field dossier, published irregularly. Dark-mode retro-sci-fi greys to
whites with a CRT phosphor-green accent; IBM Plex + VT323 typography.

== Install ==

1. Upload `phosphor-noir/` into `wp-content/themes/`.
2. Appearance → Themes → activate "Phosphor / Noir".
3. (Optional) Appearance → Customize → "CRT scanlines overlay".

== Structure ==

- style.css, theme.json — tokens, editor + front-end styles
- templates/*.html, parts/*.html — Full-Site-Editing templates (WP 6.4+)
- index.php, single.php, page.php, header.php, footer.php, comments.php —
  Classic fallbacks for non-FSE sites
- functions.php — bootstrap + one customizer option

== Changelog ==

= 1.0.0 =
* Initial release.
