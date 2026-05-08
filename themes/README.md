# Themes — Phosphor / Noir

Real, installable theme packages. The HTML mocks live in `Agent Turing UI.html`;
these are the shipping artifacts.

## WordPress — `wordpress/phosphor-noir/`

Full-Site-Editing block theme (WP 6.4+) with classic PHP fallbacks so it runs on
any WordPress install.

**Install**

```
cp -R themes/wordpress/phosphor-noir/ /path/to/wordpress/wp-content/themes/
```

Then: Appearance → Themes → activate **Phosphor / Noir**. Optional: Appearance →
Customize → "CRT scanlines overlay".

**What's inside**

- `theme.json` — color palette, type scale, layout tokens
- `style.css` — front-end + editor styles (masthead, archive, single, footer, comments, forms)
- `templates/*.html`, `parts/*.html` — FSE templates
- `index.php`, `single.php`, `page.php`, `header.php`, `footer.php`, `comments.php` — classic fallbacks
- `functions.php` — theme bootstrap + customizer
- `readme.txt` — WP.org-format theme readme

## Obsidian — `obsidian/phosphor-noir/`

Full theme: file tree, editor, graph view, callouts, code blocks, tags, frontmatter.

**Install**

```
cp -R themes/obsidian/phosphor-noir/ /path/to/vault/.obsidian/themes/
```

Then: Settings → Appearance → Themes → **Phosphor / Noir**.

**What's inside**

- `manifest.json` — theme metadata
- `theme.css` — full coverage of Obsidian's CSS variable surface

## Download bundles

Two ZIPs are generated into this folder so you can upload straight from the WP
admin / Obsidian community themes flow:

- `phosphor-noir-wordpress.zip`
- `phosphor-noir-obsidian.zip`
