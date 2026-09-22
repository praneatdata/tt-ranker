"""The RALLY stylesheet.

One string, inlined into every page — the document makes no external requests,
so there is nothing to cache and nothing to block first paint. It is written in
sections that match web/components.py, and it references tokens through custom
properties rather than repeating a hex code anywhere.

Two rules hold the look together:

  Structure is drawn with hairlines, not shadows. There is not one box-shadow
  in here; panels separate by a 1px border and a change of ground.

  Colour is rationed to the three the table gives us: the white ball for the
  one action worth taking, wood for what was earned, red for what was lost.
  Everything else is blue, so those three get noticed.
"""
from . import tokens

BASE = """
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{
  margin:0;background:var(--bg);color:var(--text);
  font:400 16px/1.55 var(--sans);-webkit-font-smoothing:antialiased;
  text-rendering:optimizeLegibility;
}
::selection{background:var(--ball);color:var(--ink)}
a{color:inherit;text-decoration:none}
:focus-visible{outline:2px solid var(--ball);outline-offset:3px;border-radius:2px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}

/* Figures are the scoreboard: mono, tabular, tightened. Never labels. */
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;letter-spacing:-.03em}
/* An inline SVG defaults to 300x150, so every icon is sized where it is used. */
.btn svg,.menu>summary svg{width:17px;height:17px;flex:none}

/* Inline-only margin and padding: a `margin` shorthand here would beat
   `section+section` on specificity and flatten every gap between sections, and
   a `padding` shorthand in the responsive rule below would reset the vertical
   padding of any section that set its own. */
.wrap{width:100%;max-width:1280px;margin-inline:auto;padding-inline:var(--s4)}
main{padding-bottom:var(--s8)}
section+section{margin-top:var(--s12)}
.hero+section{margin-top:0}   /* the hero already ends in its own padding */
section.wrap+section.wrap:has(>.note){margin-top:var(--s4)}

/* Titles: a chip worn beside a name, and the page that explains them. Each
   carries its own glyph and its own word, so it never rests on colour — and it
   is sized to sit inside a row without pushing the row around. */
.title-chip{display:inline-flex;align-items:center;gap:.28rem;flex:none;
  padding:.1rem .4rem;border:1px solid;border-radius:999px;
  font-size:.6875rem;font-weight:700;letter-spacing:.04em;white-space:nowrap}
.title-chip svg{width:12px;height:12px;flex:none}
.title-chip.up{color:var(--up);background:var(--up-bg);border-color:var(--up-line)}
.title-chip.down{color:var(--down);background:var(--down-bg);border-color:var(--down-line)}
.title-chip.ball{color:var(--ball);background:var(--ball-bg);border-color:var(--ball-line)}
.title-why{font-weight:400;letter-spacing:0;opacity:.8}
.pc-titles,.profile-titles{display:flex;flex-wrap:wrap;gap:var(--s1);margin-top:var(--s2)}
.row-who .title-chip{margin-left:var(--s2)}
.side-name+.title-chip{margin-left:.3rem}
.featured-tags .title-chip{font-size:.75rem;padding:.2rem .55rem}

.titles{list-style:none;margin:0;padding:0;display:grid;gap:var(--s3);
  grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
.title-card{display:flex;flex-direction:column;gap:var(--s2);padding:var(--s4);
  background:var(--surface);border:1px solid var(--line);border-radius:var(--r)}
.title-card-top{display:flex}
.title-blurb{margin:0;color:var(--muted);font-size:.875rem;line-height:1.5}
.title-holder{display:flex;align-items:center;gap:var(--s2);margin-top:auto;
  padding-top:var(--s3);border-top:1px solid var(--line);font-weight:600}
.title-holder.is-vacant{color:var(--muted);font-weight:400;font-style:italic}
/* Turning up: a square per day. No chart library and no canvas — a heatmap is
   a table of squares, and CSS already draws those. The four shades run through
   tokens that already exist, so the graph follows the palette rather than
   introducing a fifth colour to the page. */
.heat-wrap{display:flex;gap:var(--s2);align-items:flex-start}
.heat-days{display:grid;grid-template-rows:repeat(7,11px);gap:3px;
  padding-top:18px;font-size:.5625rem;color:var(--muted)}
.heat-day{line-height:11px}
/* The grid scrolls on a phone rather than shrinking the squares to nothing. */
.heat-scroll{overflow-x:auto;padding-bottom:var(--s1)}
.heat-grid{display:flex;gap:3px}
.heat-col{display:grid;grid-template-rows:repeat(7,11px);gap:3px}
.heat{width:11px;height:11px;border-radius:2px;background:var(--wash);display:block}
.heat-off{background:transparent}
.heat-1{background:var(--up-bg)}
.heat-2{background:var(--up-line)}
.heat-3{background:var(--wood-deep)}
.heat-4{background:var(--up)}
.heat-months{display:flex;gap:3px;margin-top:var(--s1);
  font-size:.5625rem;color:var(--muted)}
.heat-month{width:11px;flex:none;white-space:nowrap}
.heat-key{display:flex;align-items:center;gap:var(--s1);margin:var(--s3) 0 0;
  font-size:.6875rem;color:var(--muted)}
.heat-key-note{margin-left:auto}

/* Releases: a dated list, the newest marked. Read like a timeline rather than
   a table — the date is the spine and the notes hang off it. */
.footer-version{margin-top:var(--s2);font-size:.75rem}
.footer-version a{color:var(--muted);border-bottom:1px solid var(--line-mid)}
.footer-version a:hover{color:var(--text)}
.releases{list-style:none;margin:0;padding:0;display:grid;gap:var(--s8)}
.rel{display:grid;grid-template-columns:8.5rem 1fr;gap:var(--s6);
  align-items:start}
.rel-when{display:flex;flex-direction:column;gap:var(--s2);
  padding-top:.35rem;position:sticky;top:76px}
.rel-date{font-size:.8125rem;color:var(--muted);letter-spacing:-.02em}
.rel-now{align-self:start;padding:.1rem .4rem;border:1px solid var(--ball-line);
  border-radius:999px;background:var(--ball-bg);color:var(--ball);
  font-size:.625rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase}
.rel-body{min-width:0;padding-bottom:var(--s8);
  border-bottom:1px solid var(--line)}
.rel:last-child .rel-body{border-bottom:none;padding-bottom:0}
.rel-name{display:flex;flex-wrap:wrap;align-items:baseline;gap:var(--s3);
  font-size:1.35rem}
.rel-prs{font-size:.75rem;font-weight:400;color:var(--muted)}
.rel-summary{margin:var(--s3) 0 0;font-size:1rem;color:var(--text)}
.rel-notes{margin:var(--s3) 0 0;padding-left:1.1rem;color:var(--muted);
  font-size:.9375rem;line-height:1.6}
.rel-notes li{margin:.35rem 0}
.rel-summary code,.rel-notes code{padding:.1rem .3rem;background:var(--raised);border-radius:var(--r-sm);color:var(--text)}

/* The micro-label that titles nearly every block on the page. */
.eyebrow{margin:0;font-size:.6875rem;font-weight:700;letter-spacing:.17em;
  text-transform:uppercase;color:var(--muted)}
.eyebrow.bright{color:var(--ball)}
h1,h2,h3{margin:0;font-weight:700;letter-spacing:-.025em;line-height:1.05}
h2{font-size:1.35rem;letter-spacing:-.02em}
.section-head{display:flex;flex-wrap:wrap;align-items:baseline;
  justify-content:space-between;gap:var(--s1) var(--s4);margin:0 0 var(--s4);
  padding-bottom:var(--s3);border-bottom:1px solid var(--line-mid)}
.section-head .eyebrow{margin-left:auto}
.note{margin:0 0 var(--s4);max-width:60ch;color:var(--muted);font-size:.875rem;line-height:1.55}
/* The format caveat belongs to the tabs above it, so it runs their width. */
.note.wide{max-width:none}
"""

NAV = """
.nav{position:sticky;top:0;z-index:20;background:var(--nav-bg);
  border-bottom:1px solid var(--line-mid);backdrop-filter:blur(12px)}
@supports not (backdrop-filter:blur(2px)){.nav{background:var(--bg)}}
.nav-in{display:flex;align-items:center;gap:var(--s4);min-height:60px}
.brand{display:flex;align-items:center;gap:.55rem;line-height:1;
  padding:var(--s2) 0;margin-right:var(--s2)}
.brand-words{display:flex;flex-direction:column;justify-content:center}
/* The one image on the site. Round, because the mark is — a square box around
   it would read as a missing asset rather than a logo. */
.vmock{width:28px;height:28px;flex:none;border-radius:50%;display:block}
.brand-mark{display:flex;align-items:center;gap:.45rem;font-size:1.0625rem;
  font-weight:700;letter-spacing:.2em;text-transform:uppercase}
.brand-mark .ball{width:7px;height:7px;border-radius:50%;background:var(--ball);
  flex:none;margin-bottom:.15em}
.brand-sub{margin-top:.3rem;font-size:.5625rem;font-weight:600;letter-spacing:.19em;
  text-transform:uppercase;color:var(--muted)}
.nav-links{display:none;align-items:center;gap:var(--s1);margin-left:var(--s6)}
.nav-link{position:relative;padding:.5rem .7rem;font-size:.8125rem;font-weight:600;
  letter-spacing:.09em;text-transform:uppercase;color:var(--muted);
  transition:color .16s ease}
.nav-link::after{content:"";position:absolute;left:.7rem;right:.7rem;bottom:-1px;
  height:2px;background:var(--ball);transform:scaleX(0);transform-origin:left;
  transition:transform .18s ease}
.nav-link:hover{color:var(--text)}
.nav-link.on{color:var(--text)}
.nav-link.on::after{transform:scaleX(1)}
.nav-link.soon{color:var(--soon);cursor:default}
.nav-link.soon:hover{color:var(--soon)}
.nav-link .soon-tag{margin-left:.35rem;font-size:.5rem;letter-spacing:.12em;
  color:var(--soon);vertical-align:.15em}
.nav-cta{margin-left:auto;display:flex;align-items:center;gap:var(--s2)}

/* Mobile menu: a <details> disclosure, so it opens with no script and is
   keyboard-operable for free. */
.menu{position:relative;margin-left:auto}
.menu>summary{list-style:none;display:flex;align-items:center;justify-content:center;
  width:38px;height:38px;border:1px solid var(--line-mid);border-radius:var(--r-btn);
  color:var(--text);cursor:pointer}
.menu>summary::-webkit-details-marker{display:none}
.menu[open]>summary{background:var(--raised)}
.menu-panel{position:absolute;right:0;top:calc(100% + 8px);min-width:190px;
  padding:var(--s2);background:var(--surface);border:1px solid var(--line-mid);
  border-radius:var(--r);display:grid;gap:2px}
.menu-panel .nav-link{padding:.6rem .7rem;border-radius:var(--r-sm)}
.menu-panel .nav-link.on{background:var(--raised)}
.menu-panel .nav-link::after{display:none}

/* The theme picker is the same disclosure as the menu, so it needs no rules of
   its own beyond the swatches. Each swatch is a table seen from above: the
   ground, the white edge, and the two accents laid across it. */
.themes{margin-left:0}
.themes .menu-panel{min-width:200px}
.theme-opt{display:flex;align-items:center;gap:var(--s3);width:100%;
  padding:.5rem .6rem;border:0;border-radius:var(--r-sm);background:transparent;
  color:var(--muted);font:600 .8125rem/1 var(--sans);text-align:left;cursor:pointer}
.theme-opt:hover{background:var(--raised);color:var(--text)}
.theme-opt.on{background:var(--raised);color:var(--text)}
/* The held option is marked by the ball as well as by the fill, because the
   fill alone is a colour difference and colour is never the only signal. */
.theme-opt.on::after{content:"";width:7px;height:7px;margin-left:auto;
  border-radius:50%;background:var(--ball);flex:none}
.swatch{position:relative;display:flex;align-items:flex-end;gap:2px;
  width:26px;height:18px;padding:2px;border:1px solid;border-radius:3px;flex:none}
.swatch span{display:block;flex:1;height:5px;border-radius:1px}
"""

BUTTONS = """
.btn{display:inline-flex;align-items:center;gap:.45rem;padding:.6rem .95rem;
  white-space:nowrap;
  border:1px solid var(--line-mid);border-radius:var(--r-btn);background:transparent;
  color:var(--text);font:inherit;font-size:.8125rem;font-weight:600;
  letter-spacing:.09em;text-transform:uppercase;cursor:pointer;
  transition:background .16s ease,border-color .16s ease,transform .16s ease,color .16s ease}
.btn:hover{background:var(--raised);border-color:var(--line-strong)}
.btn:active{transform:translateY(1px)}
.btn-primary{background:var(--ball);border-color:var(--ball);color:var(--ink);font-weight:700}
.btn-primary:hover{background:var(--ball-hover);border-color:var(--ball-hover);color:var(--ink)}
.btn-icon{padding:.55rem;width:38px;height:38px;justify-content:center}
@media (max-width:47.99rem){.btn-wide-only{display:none}}
"""

HERO = """
.hero{position:relative;padding:var(--s12) 0 var(--s8);overflow:hidden}
.hero-arc{position:absolute;right:-4%;top:-22%;width:min(520px,72%);height:auto;
  color:var(--ball);opacity:.20;pointer-events:none}
.hero-in{position:relative}
.hero h1{margin:var(--s3) 0 0;font-size:clamp(2.75rem,11vw,5.25rem);
  text-transform:uppercase;letter-spacing:-.04em}
.hero .tagline{margin:var(--s3) 0 0;font-size:1.0625rem;color:var(--muted);max-width:44ch}
.hero .hero-note{margin:var(--s3) 0 0;max-width:56ch;color:var(--muted);font-size:.9375rem}
.hero-stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
  gap:var(--s6) var(--s4);margin:var(--s8) 0 0;padding:var(--s6) 0 0;
  border-top:1px solid var(--line-mid);list-style:none}
.hero-stats li{min-width:0}
.hero-stats .stat-value{display:block;font-size:1.75rem;font-weight:700;letter-spacing:-.03em}
.hero-stats .stat-label{display:block;margin-top:.2rem;font-size:.625rem;font-weight:700;
  letter-spacing:.17em;text-transform:uppercase;color:var(--muted)}

.live{display:inline-flex;align-items:center;gap:.45rem}
.live-dot{width:7px;height:7px;border-radius:50%;background:var(--ball);flex:none;
  animation:pulse 2.6s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.45;transform:scale(.82)}}
"""

TABS = """
/* The tabs are the width of the board they sit above, split evenly — a
   segmented control across the table, not a cluster in the corner. */
.tabs{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;gap:var(--s1);
  margin:0 0 var(--s6);padding:4px;border:1px solid var(--line-mid);
  border-radius:var(--r);background:var(--surface);width:100%}
.tabs a{padding:.55rem .9rem;border-radius:var(--r-sm);font-size:.75rem;font-weight:700;
  letter-spacing:.11em;text-transform:uppercase;color:var(--muted);white-space:nowrap;
  text-align:center;transition:background .16s ease,color .16s ease}
.tabs a:hover{color:var(--text)}
.tabs a.on{background:var(--ball);color:var(--ink)}
/* Two controls, one line — and not the same control twice: the board toggle
   is a mode, so it carries an icon and a quieter fill. */
/* Stacked, not side by side: the format tabs are the width of the board they
   filter, and the board toggle is only as wide as its own two words. */
.controls{display:flex;flex-direction:column;align-items:stretch;gap:var(--s3)}
.controls .tabs{margin-bottom:0}
.controls .board-toggle{align-self:flex-start;width:auto}
.controls+*{margin-top:var(--s6)}
.board-toggle{grid-auto-columns:auto;width:auto;flex:0 0 auto;
  background:transparent;border-color:var(--line-strong)}
.board-toggle .toggle-icon{display:flex;align-items:center;padding-left:.45rem;
  color:var(--muted)}
.board-toggle .toggle-icon svg{width:14px;height:14px}
.board-toggle a.on{background:var(--raised);color:var(--text)}
"""

FEATURED = """
.featured{position:relative;margin-top:var(--s6);padding:var(--s6);overflow:hidden;
  background:var(--surface);border:1px solid var(--line-mid);border-radius:var(--r-lg)}
.featured::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
  background:var(--paddle)}
.featured-net{position:absolute;right:-4%;bottom:-18%;width:min(230px,34%);height:58%;
  color:var(--ball);opacity:.09;pointer-events:none}
.featured-in{position:relative;display:grid;gap:var(--s6)}
.featured-rank{display:flex;align-items:baseline;gap:var(--s3)}
.featured-rank .hash{font-size:clamp(3.5rem,17vw,6.5rem);font-weight:700;line-height:.78;
  color:var(--ghost);-webkit-text-stroke:1.5px var(--ghost-line)}
.featured-who{display:flex;align-items:center;gap:var(--s3);min-width:0}
.featured-name{font-size:clamp(1.75rem,7vw,2.5rem);font-weight:700;letter-spacing:-.03em;
  line-height:1.05;overflow-wrap:anywhere}
.featured-rating{display:flex;flex-direction:column;justify-content:center}
.featured-rating .value{font-size:clamp(3.25rem,15vw,5.5rem);font-weight:700;line-height:.85}
.featured-meta{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s3) var(--s6);
  padding-top:var(--s4);border-top:1px solid var(--line-mid)}
.featured-meta .pair{display:flex;flex-direction:column;gap:.2rem}
.featured-meta .pair-value{font-size:1.0625rem;font-weight:700;letter-spacing:-.02em}
.featured-meta .pair-label{font-size:.625rem;font-weight:700;letter-spacing:.16em;
  text-transform:uppercase;color:var(--muted)}
.featured-tags{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s2) var(--s3);
  margin-top:var(--s3)}
.featured-rating .move{justify-content:flex-start;font-size:.8125rem;margin-top:.35rem}
.featured.is-empty{border-style:dashed}
.featured.is-empty .featured-name{font-size:1.5rem}
"""

BOARD = """
.board{list-style:none;margin:0;padding:0;position:relative}
/* The centre line: the ranks sit on it the way the line runs down the table. */
.board::before{content:"";position:absolute;left:calc(var(--s2) + 1.05rem);top:0;
  bottom:0;width:1px;background:var(--line-mid)}
.row{position:relative;display:grid;align-items:center;gap:.3rem var(--s3);
  padding:var(--s3) var(--s2);border-bottom:1px solid var(--line);border-radius:var(--r-sm);
  grid-template-columns:2.1rem minmax(0,1fr) auto;
  grid-template-areas:"rank who score" "rank meta score" "rank form score";
  transition:background .16s ease}
.row:hover{background:var(--raised)}
.row:last-child{border-bottom:none}
.row-rank{grid-area:rank;justify-self:center;display:flex;flex-direction:column;
  align-items:center;gap:.15rem;z-index:1;background:var(--bg);padding:.2rem 0;
  transition:background .16s ease}
.row:hover .row-rank{background:var(--raised)}
.row-rank .pos{font-size:.9375rem;font-weight:700;color:var(--muted)}
.row.is-top .row-rank .pos{color:var(--wood)}
.row-who{grid-area:who;display:flex;align-items:center;gap:var(--s3);min-width:0}
.row-name{display:block;font-weight:600;letter-spacing:-.012em;overflow-wrap:anywhere}
/* The record is a column of its own once there is room for one, and a line
   under the name when there isn't. */
.row-meta{grid-area:meta;display:flex;flex-wrap:wrap;align-items:center;gap:.45rem;
  padding-left:2.6rem;font-size:.75rem;color:var(--muted)}
.row-form{grid-area:form;display:flex;flex-wrap:wrap;align-items:center;gap:.4rem .6rem;
  padding-left:2.6rem}
.row-score{grid-area:score;display:flex;flex-direction:column;align-items:flex-end;
  justify-content:center;gap:.15rem;min-width:0;text-align:right;white-space:nowrap}
.row-score .rating{font-size:1.375rem;font-weight:700}

.placing{display:flex;flex-wrap:wrap;gap:var(--s2);margin:0;padding:0;list-style:none}
.placing li{display:flex;align-items:baseline;gap:.45rem;padding:.4rem .7rem;
  border:1px solid var(--line-mid);border-radius:var(--r-sm);font-size:.8125rem}
.placing .need{font-size:.75rem;color:var(--muted)}
"""

PIECES = """
/* Avatar: a monogram, tinted per player and never louder than the name. */
.avatar{display:inline-flex;align-items:center;justify-content:center;flex:none;
  width:32px;height:32px;border-radius:50%;border:1px solid currentColor;
  font-family:var(--mono);font-size:.75rem;font-weight:700;letter-spacing:0;
  text-transform:uppercase}
.avatar-lg{width:52px;height:52px;font-size:1.125rem}
.avatar-sm{width:24px;height:24px;font-size:.625rem}

/* Movement: the glyph carries the meaning, so colour is never the only signal. */
.move{display:inline-flex;align-items:center;gap:.25rem;font-size:.75rem;color:var(--muted)}
.move.up{color:var(--up)}
.move.down{color:var(--down)}
.move .num{font-size:.8125rem}
.rank-move{font-size:.5625rem;font-weight:700;letter-spacing:.02em;color:var(--muted)}
.rank-move.up{color:var(--up)}
.rank-move.down{color:var(--down)}

/* Form: five results, most recent last. The letter is the signal; the tint
   is the reinforcement. */
.form{display:flex;align-items:center;gap:3px}
.form-cell{display:inline-flex;align-items:center;justify-content:center;
  width:19px;height:19px;border-radius:4px;font-family:var(--mono);font-size:.625rem;
  font-weight:700;border:1px solid transparent}
.form-cell.w{background:var(--up-bg);border-color:var(--up-line);color:var(--up)}
.form-cell.l{background:var(--down-bg);border-color:var(--down-line);color:var(--down)}
.form-cell.d{background:var(--wash);border-color:var(--line-mid);color:var(--muted)}
.form-label{font-size:.5625rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;
  color:var(--muted)}

/* Streak: earned, so it is allowed a little colour. Icon, not emoji. */
.streak{display:inline-flex;align-items:center;gap:.3rem;padding:.2rem .45rem;
  white-space:nowrap;
  border-radius:var(--r-sm);font-size:.6875rem;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;border:1px solid transparent}
.streak.hot{color:var(--up);background:var(--up-bg);border-color:var(--up-line)}
.streak.cold{color:var(--down);background:var(--down-bg);border-color:var(--down-line)}
.streak svg{width:11px;height:11px}
.tag{display:inline-flex;align-items:center;padding:.18rem .42rem;border-radius:4px;
  border:1px solid var(--line-mid);font-size:.5625rem;font-weight:700;letter-spacing:.14em;
  text-transform:uppercase;color:var(--muted)}
"""

MATCHES = """
.matches{display:grid;gap:var(--s3)}
.match{padding:var(--s4);background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r);transition:border-color .16s ease,background .16s ease}
.match:hover{border-color:var(--line-mid);background:var(--raised)}
.match-top{display:flex;align-items:center;gap:var(--s2);margin-bottom:var(--s3)}
.match-top .when{margin-left:auto;font-size:.6875rem;letter-spacing:.06em;
  text-transform:uppercase;color:var(--muted)}
.match-body{display:grid;grid-template-columns:minmax(0,1fr);align-items:center;
  gap:var(--s2)}
.side{display:flex;align-items:center;justify-content:space-between;gap:var(--s3);
  min-width:0}
.side-names{display:flex;align-items:center;gap:.45rem;min-width:0;flex-wrap:wrap}
.side-name{font-weight:600;font-size:.9375rem;overflow-wrap:anywhere;color:var(--muted)}
.side.won .side-name{color:var(--text);font-weight:700}
.side-delta-row{display:flex;flex-wrap:wrap;gap:.45rem;font-size:.75rem}
.side.b .side-delta-row{justify-content:flex-end}
.side-delta{font-size:.75rem;color:var(--muted);font-family:var(--mono);letter-spacing:-.02em}
.side-delta.up{color:var(--up)}
.side-delta.down{color:var(--down)}
.match-score{display:flex;align-items:center;justify-content:center;gap:.4rem;
  font-size:1.5rem;font-weight:700;letter-spacing:-.04em;padding:.2rem 0;
  border-block:1px solid var(--line);margin-block:var(--s1)}
.match-score .sep{color:var(--muted);font-weight:400}
.match-games{display:flex;flex-wrap:wrap;gap:.3rem;margin-top:var(--s3);
  padding-top:var(--s3);border-top:1px solid var(--line)}
.match-games span{padding:.12rem .4rem;border:1px solid var(--line-mid);border-radius:4px;
  font-size:.75rem;color:var(--muted)}

.filters{display:flex;flex-direction:column;align-items:stretch;gap:var(--s3);
  margin:0 0 var(--s4)}
/* The inputs take the row, the chips take the next one — so the search can
   spread into whatever width the date leaves it. */
.filters-top{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s2)}
.filters-top .search{flex:1 1 18rem;max-width:none}
.filter-date{gap:0}
.filter-date input{min-width:9.5rem}
.filters-chips{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s2)}
.filters select,.filters input,.filters button,.filters a{font:inherit;font-size:.8125rem;
  color:var(--text);background:transparent;border:1px solid var(--line-mid);
  border-radius:var(--r-sm);padding:.4rem .6rem;transition:border-color .16s ease,
  background .16s ease,color .16s ease}
.filters select,.filters input{color:var(--text);background:var(--surface)}
.filters input{color-scheme:inherit}
.filters a{font-size:.6875rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
  color:var(--muted)}
.filters a:hover{color:var(--text);border-color:var(--line-strong)}
.filters a.on{background:var(--ball);border-color:var(--ball);color:var(--ink)}
.filters .sep{width:1px;height:1.4rem;background:var(--line-mid);margin:0 .2rem}
.filter-group{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s2)}
.filter-label{font-size:.5625rem;font-weight:700;letter-spacing:.16em;
  text-transform:uppercase;color:var(--muted);margin-right:.1rem}
/* On a phone each group gets its own line and the rules between them go:
   the labels already say where one ends and the next begins. */
@media (max-width:47.99rem){
  .filters{gap:var(--s2) var(--s2)}
  .filters .sep{display:none}
  .filter-group{width:100%}
  .filters select,.filters input[type=date]{flex:1 1 40%}
}
.count{margin:0 0 var(--s3);font-size:.8125rem;color:var(--muted)}

.empty{padding:var(--s12) var(--s6);text-align:center;border:1px dashed var(--line-mid);
  border-radius:var(--r-lg)}
.empty h3{font-size:1.25rem;text-transform:uppercase;letter-spacing:-.02em}
.empty p{margin:var(--s2) 0 var(--s4);color:var(--muted)}
"""

FOOTER = """
.footer{margin-top:var(--s16);padding:var(--s8) 0 var(--s12);
  border-top:1px solid var(--line-mid)}
.footer-in{display:grid;gap:var(--s6)}
.footer-links{display:flex;flex-wrap:wrap;gap:var(--s4);list-style:none;margin:0;padding:0}
.footer-links li{font-size:.75rem;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase}
.footer-links a{color:var(--muted)}
.footer-links a:hover{color:var(--text)}
.footer-links .soon{color:var(--soon-dim)}
.footer-note{margin:0;max-width:60ch;font-size:.8125rem;color:var(--muted)}
.footer-note+.footer-note{margin-top:var(--s2)}
.footer code{font-family:var(--mono);font-size:.8125rem;color:var(--text)}
"""

MOTION = """
/* Sections arrive once, briefly. The elements are visible by default and the
   animation only plays forward from a hidden state, so switching motion off
   can never leave anything stuck at opacity 0. */
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.rise{animation:rise .38s cubic-bezier(.2,.7,.3,1) both}
.rise-1{animation-delay:.04s}
.rise-2{animation-delay:.08s}
.rise-3{animation-delay:.12s}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation:none!important;transition:none!important;
    scroll-behavior:auto!important}
}
"""

PAGES = """
/* The wall of shame. Built from the same parts as the ladder's rungs — a rank,
   a name, some figures — because it is read the same way, and giving it a look
   of its own would make it feel like a different kind of claim than it is.
   The one borrowed colour is the down tone on the worst row, which the board
   already uses for a rating going the wrong way. */
.shame{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;
  gap:var(--s2)}
.shame-row{display:grid;grid-template-columns:auto auto 1fr auto;align-items:center;
  gap:var(--s3);padding:var(--s3) var(--s4);background:var(--surface);
  border:1px solid var(--line);border-radius:var(--r)}
.shame-row.is-worst{border-color:var(--down-line);background:var(--down-bg)}
.shame-row .rank{color:var(--muted);font-size:.875rem;font-variant-numeric:tabular-nums}
.shame-row .who{display:flex;align-items:center;gap:var(--s2);min-width:0}
.shame-name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.shame-tallies{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;
  gap:var(--s2) var(--s3);justify-content:flex-end}
.shame-tally{display:flex;align-items:baseline;gap:.35rem;font-size:.8125rem}
.shame-tally .n{font-weight:700;font-variant-numeric:tabular-nums}
.shame-tally .k{color:var(--muted)}
.shame-score{font-weight:700;font-size:1.125rem;font-variant-numeric:tabular-nums;
  min-width:2.5ch;text-align:right}
.shame-key{padding:var(--s4);background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r)}
.shame-key-head{margin:0 0 var(--s3);font-weight:600;font-size:.875rem}
.shame-key ul{list-style:none;margin:0;padding:0;display:flex;
  flex-direction:column;gap:var(--s2)}
.shame-key-item{display:grid;grid-template-columns:8rem 1fr auto;gap:var(--s3);
  align-items:baseline;font-size:.875rem}
.shame-key-item .k{font-weight:600}
.shame-key-item .d{color:var(--muted)}
.shame-key-item .w{color:var(--muted);font-variant-numeric:tabular-nums}

/* Secondary pages: the ladder's hero at working size. */
.page-head{padding:var(--s12) 0 var(--s8)}
.page-head h1{margin:var(--s2) 0 0;font-size:clamp(2.25rem,8vw,3.5rem);
  text-transform:uppercase;letter-spacing:-.035em}
.page-head .tagline{margin:var(--s3) 0 0;max-width:52ch;color:var(--muted);font-size:1rem}
.page-head .tabs{margin-top:var(--s6)}
.head-top{display:grid;gap:var(--s6);align-items:stretch}
.head-title{min-width:0}
.stat-tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--s3);
  margin:0;padding:0;list-style:none}
/* The figure at the top, its name at the foot: the box fills the height of the
   title beside it rather than floating in the middle of it. */
.stat-tile{display:flex;flex-direction:column;justify-content:space-between;
  gap:var(--s4);padding:var(--s4);background:var(--surface);
  border:1px solid var(--line-mid);border-radius:var(--r);
  transition:border-color .16s ease,background .16s ease}
.stat-tile:hover{border-color:var(--line-strong);background:var(--raised)}
.stat-tile .v{display:block;font-size:2rem;font-weight:700;letter-spacing:-.03em;
  line-height:1}
.stat-tile .l{display:block;font-size:.625rem;font-weight:700;
  letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.page-head .head-cta{margin-top:var(--s6)}
/* Controls belong to the content below them, so a header that ends in a
   search or a picker sits closer to it. */
.page-head:has(.find){padding-bottom:var(--s4)}
.page-head:has(.find)+section{margin-top:var(--s6)}
.page-head .hero-stats{margin-top:var(--s6)}

/* Matches: a day at a time. */
.day+.day{margin-top:var(--s8)}
.day-head{display:flex;align-items:baseline;gap:var(--s3);margin:0 0 var(--s4);
  padding-bottom:var(--s2);border-bottom:1px solid var(--line)}
.day-head h3{font-size:.8125rem;font-weight:700;letter-spacing:.14em;
  text-transform:uppercase}
.day-head time{font-size:.75rem;color:var(--muted)}
.day-head .day-count{margin-left:auto;font-size:.8125rem;color:var(--muted)}
/* Marked the way the leader's panel is marked, so "featured" reads as one
   idea across the page rather than two different treatments. */
.motw .match{border-color:var(--line-mid);border-left:3px solid var(--paddle);
  background:var(--surface)}
.motw .match-score{font-size:2rem}
.motw .side-name{font-size:1.0625rem}

/* Players: a grid of cards, each a link to the person. */
.pc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));
  gap:var(--s3)}
.pc{display:block;padding:var(--s4);background:var(--surface);
  border:1px solid var(--line);border-radius:var(--r);
  transition:border-color .16s ease,background .16s ease,transform .16s ease}
a.pc:hover{border-color:var(--line-strong);background:var(--raised);transform:translateY(-2px)}
.pc-top{display:flex;align-items:center;gap:var(--s2);min-height:24px}
.pc-rank{font-size:.8125rem;font-weight:700;color:var(--muted)}
.pc-rank.pc-placing{font-family:var(--sans);font-size:.625rem;letter-spacing:.14em;
  text-transform:uppercase}
.pc-top .streak{margin-left:auto}
.pc-who{display:flex;align-items:center;gap:var(--s3);margin-top:var(--s3);min-width:0}
.pc-name{font-size:1.125rem;font-weight:700;letter-spacing:-.02em;overflow-wrap:anywhere}
.pc-rating{display:flex;align-items:baseline;gap:var(--s2);margin-top:var(--s3)}
/* Direct child only: the movement beside it carries a .num of its own, and it
   is not the headline. */
.pc-rating>.num{font-size:1.75rem;font-weight:700}
.pc-meta{display:flex;flex-wrap:wrap;gap:var(--s1) var(--s3);margin-top:var(--s1);
  color:var(--muted);font-size:.8125rem}
.pc-form{margin-top:var(--s3)}

/* One player. */
.profile{padding:var(--s12) 0 var(--s6)}
.profile-in{display:grid;gap:var(--s4);align-items:center}
.profile-rank .hash{font-size:clamp(2.5rem,12vw,4.5rem);font-weight:700;line-height:.8;
  color:var(--ghost);-webkit-text-stroke:1.5px var(--ghost-line)}
.profile-rank .hash.is-placing{-webkit-text-stroke:1.5px var(--line-strong);
  color:transparent}
.profile-who{min-width:0}
.profile-who .featured-name{margin:var(--s2) 0 0}
.profile-who .tabs{margin:var(--s4) 0 0}
/* The figures belong to the header, so they sit right under it rather than a
   whole section's gap away. */
.profile+section{margin-top:0}
.profile-actions{margin:var(--s4) 0 0}
.profile-actions .btn svg{width:15px;height:15px}
.profile-figures{display:flex;flex-wrap:wrap;gap:var(--s4) var(--s8);
  padding:var(--s6) 0;border-top:1px solid var(--line-mid);
  border-bottom:1px solid var(--line-mid)}
.profile-figures .pair{display:flex;flex-direction:column;gap:.2rem}
.profile-figures .pair-value{font-size:1.125rem;font-weight:700;letter-spacing:-.02em}
.profile-figures .pair-label{font-size:.625rem;font-weight:700;letter-spacing:.16em;
  text-transform:uppercase;color:var(--muted)}
.profile-tags{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s3);
  margin-top:var(--s4)}

/* Rating over time: one line, every point a rating that really applied. */
.chart{position:relative;margin:0;padding:var(--s4) 0 0}
.chart svg{display:block;width:100%;height:clamp(130px,20vw,230px);overflow:visible}
/* The line draws itself once, left to right. The resting state is a finished
   line — the animation only moves the offset — so with motion switched off the
   chart is simply there, rather than invisible. */
.chart-line{fill:none;stroke:var(--up);stroke-width:2;stroke-linejoin:round;
  stroke-linecap:round;vector-effect:non-scaling-stroke;
  stroke-dasharray:2400;stroke-dashoffset:0;animation:draw .9s ease-out}
@keyframes draw{from{stroke-dashoffset:2400}to{stroke-dashoffset:0}}
.chart-area{animation:fade .9s ease-out}
.chart-dot{animation:fade .6s .5s backwards}
@keyframes fade{from{opacity:0}to{opacity:1}}
/* The end point is a round-capped zero-length line, not a circle: a circle
   turns into an ellipse once the viewBox stops preserving its shape. */
.chart-dot{stroke:var(--up);stroke-width:9;stroke-linecap:round;
  vector-effect:non-scaling-stroke}
.chart-area{fill:var(--up-bg);stroke:none}
.chart.down .chart-line{stroke:var(--down)}
.chart.down .chart-area{fill:var(--down-bg)}
.chart.down .chart-dot{stroke:var(--down)}
.chart-scale{position:absolute;right:0;top:var(--s4);bottom:1.6rem;display:flex;
  flex-direction:column;justify-content:space-between;align-items:flex-end;
  font-size:.6875rem;color:var(--muted);pointer-events:none}
.chart-foot{margin-top:var(--s2);font-size:.75rem;color:var(--muted)}
.chart-move{margin:var(--s2) 0 0}

/* Two players, side by side. */
/* Search on the left, the compare switch on the right, on one line. */
.find{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s3);
  justify-content:space-between;margin-top:var(--s6)}
.find .search{flex:1 1 18rem;max-width:34rem}
.compare-toggle.on{background:var(--ball);border-color:var(--ball);color:var(--ink)}
.compare-toggle svg{width:15px;height:15px}

.compare-bar{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s2);
  margin-top:var(--s3);padding:var(--s3);border:1px solid var(--line-mid);
  border-radius:var(--r);background:var(--surface)}
.compare-bar select{font:inherit;font-size:.8125rem;color:var(--text);
  background:var(--raised);border:1px solid var(--line-mid);
  border-radius:var(--r-sm);padding:.45rem .55rem;max-width:10rem}
.compare-bar .btn-primary{margin-left:auto}
.cmp-add{display:inline-flex;align-items:center;justify-content:center;width:34px;
  height:34px;padding:0;color:var(--text);background:transparent;cursor:pointer;
  border:1px dashed var(--line-strong);border-radius:var(--r-sm);
  transition:background .16s ease,border-color .16s ease}
.cmp-add:hover{background:var(--raised);border-color:var(--ball)}
.cmp-add svg{width:16px;height:16px}
.cmp-hint{flex:1 0 100%;margin:0;font-size:.75rem;color:var(--muted)}

/* A card while comparing: the same card, picked or not. */
button.pc{width:100%;text-align:left;font:inherit;color:inherit;cursor:pointer}
.pc-pick{position:relative}
.pc-pick.is-picked{border-color:var(--ball);background:var(--raised)}
.pc-pick.is-picked::after{content:"";position:absolute;top:var(--s3);right:var(--s3);
  width:10px;height:10px;border-radius:50%;background:var(--ball)}

/* The comparison, where it was asked for. */
.dialog{width:min(1180px,94vw);max-height:88vh;padding:0;color:var(--text);
  background:var(--bg);border:1px solid var(--line-strong);border-radius:var(--r-lg);
  overflow:hidden}
.dialog::backdrop{background:var(--scrim)}
.dialog-bar{display:flex;align-items:center;justify-content:space-between;
  gap:var(--s3);padding:var(--s3) var(--s4);border-bottom:1px solid var(--line-mid);
  background:var(--surface)}
.dialog-open{font-size:.6875rem;font-weight:700;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted)}
.dialog-open:hover{color:var(--text)}
.dialog-close{width:32px;height:32px;padding:0;font:inherit;color:var(--text);
  background:transparent;border:1px solid var(--line-mid);border-radius:var(--r-sm);
  cursor:pointer;transition:background .16s ease}
.dialog-close:hover{background:var(--raised)}
.dialog-body{max-height:calc(88vh - 56px);overflow-y:auto;padding:var(--s4) 0 var(--s8)}
.dialog-body .wrap{padding-inline:var(--s4)}
.dialog-body section+section{margin-top:var(--s8)}
.cmp-bare-head{padding-top:var(--s2)}
.cmp-head{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
  gap:var(--s4);margin-top:var(--s4)}
.cmp-side{display:flex;flex-direction:column;gap:.35rem;min-width:0;
  padding:var(--s4);background:var(--surface);border:1px solid var(--line-mid);
  border-radius:var(--r)}
.cmp-name{font-size:clamp(1.25rem,5vw,2rem);font-weight:700;letter-spacing:-.03em;
  overflow-wrap:anywhere}
.cmp-name:hover{color:var(--ball)}
.cmp-rank{font-size:.625rem;font-weight:700;letter-spacing:.16em;
  text-transform:uppercase;color:var(--muted)}
.cmp-rating{font-size:clamp(2rem,8vw,3rem);font-weight:700;line-height:1}
.cmp-v{font-size:.8125rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  color:var(--muted);padding:0 var(--s2)}
.cmp-scroll{overflow-x:auto}
/* Two players fit a phone; three or four are a table, and a table is allowed
   to scroll inside its own box rather than dragging the page sideways. */
.cmp-table{width:100%;border-collapse:collapse;min-width:22rem}
.cmp-table.cmp-of-3{min-width:30rem}
.cmp-table.cmp-of-4{min-width:38rem}
.cmp-table th,.cmp-table td{padding:var(--s3);border-bottom:1px solid var(--line);
  text-align:left}
.cmp-table thead th{font-size:.75rem;font-weight:700;letter-spacing:.06em;
  color:var(--text);border-bottom:1px solid var(--line-mid)}
.cmp-table tbody th{font-size:.625rem;font-weight:700;letter-spacing:.16em;
  text-transform:uppercase;color:var(--muted);white-space:nowrap}
.cmp-table tr:last-child th,.cmp-table tr:last-child td{border-bottom:none}
.cmp-cell{font-size:1.0625rem;font-weight:600}
.cmp-self{color:var(--line-strong);text-align:center}
.cmp-none{color:var(--muted)}
.cmp-drawn{margin-left:.35rem;font-size:.75rem;color:var(--muted)}
/* The side in front keeps full weight and the other steps back — a difference
   you can see without being told which colour means what. */
.cmp-cell{color:var(--muted)}
.cmp-cell.leads{color:var(--text);font-weight:700}
.cmp-cell.leads::after{content:"";display:inline-block;width:6px;height:6px;
  margin-left:.45rem;border-radius:50%;background:var(--wood);vertical-align:.2em}
.cmp-matches{margin-top:var(--s4)}
.chart-pair .chart-line.l0{stroke:var(--ball)}
.chart-pair .chart-dot.l0{stroke:var(--ball)}
.chart-pair .chart-line.l1{stroke:var(--wood)}
.chart-pair .chart-dot.l1{stroke:var(--wood)}
.chart-pair .chart-line.l2{stroke:var(--paddle)}
.chart-pair .chart-dot.l2{stroke:var(--paddle)}
.chart-pair .chart-line.l3{stroke:var(--avatar-3)}
.chart-pair .chart-dot.l3{stroke:var(--avatar-3)}
.legend-key.l2::before{background:var(--paddle)}
.legend-key.l3::before{background:var(--avatar-3)}
.legend{display:flex;flex-wrap:wrap;gap:var(--s4);margin:var(--s3) 0 0}
.legend-key{display:inline-flex;align-items:center;gap:.4rem;font-size:.8125rem;
  color:var(--muted)}
.legend-key::before{content:"";width:14px;height:2px;border-radius:2px}
.legend-key.l0::before{background:var(--ball)}
.legend-key.l1::before{background:var(--wood)}

/* Head to head. */
.rivals{display:flex;flex-wrap:wrap;gap:var(--s2);margin:0 0 var(--s4)}
.rival{display:inline-flex;align-items:center;gap:.4rem;padding:.35rem .6rem;
  border:1px solid var(--line-mid);border-radius:var(--r-sm);font-size:.8125rem;
  transition:border-color .16s ease,background .16s ease}
.rival:hover{border-color:var(--line-strong);background:var(--raised)}
.rival.on{background:var(--raised);border-color:var(--ball)}
.rival-count{font-size:.75rem;color:var(--muted)}
.h2h{padding:var(--s6);background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r)}
.h2h-sides{display:flex;align-items:center;justify-content:space-between;gap:var(--s4)}
.h2h-side{display:flex;align-items:center;gap:var(--s2);min-width:0}
.h2h-side.b{flex-direction:row-reverse;text-align:right}
.h2h-name{font-weight:600;overflow-wrap:anywhere}
.h2h-wins{font-size:1.75rem;font-weight:700}
.h2h-bar{display:flex;height:6px;margin:var(--s4) 0 var(--s3);border-radius:3px;
  overflow:hidden;background:var(--raised)}
.h2h-bar span{display:block;height:100%;transition:width .4s cubic-bezier(.2,.7,.3,1)}
.h2h-bar .won{background:var(--up)}
.h2h-bar .drew{background:var(--wash-strong)}
.h2h-bar .lost{background:var(--down)}
.h2h-line{margin:0;color:var(--muted);font-size:.8125rem}
.h2h-recent{display:flex;align-items:center;gap:3px;margin-top:var(--s3)}
.h2h-recent .form-label{margin-right:.3rem}
.h2h-cell{display:inline-flex;align-items:center;justify-content:center;width:19px;
  height:19px;border-radius:4px;font-family:var(--mono);font-size:.625rem;
  font-weight:700;border:1px solid transparent}
.h2h-cell.w{background:var(--up-bg);border-color:var(--up-line);color:var(--up)}
.h2h-cell.l{background:var(--down-bg);border-color:var(--down-line);color:var(--down)}
.h2h-cell.d{background:var(--wash);border-color:var(--line-mid);color:var(--muted)}

/* The numbers. */
.sc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
  gap:var(--s3);margin:0;padding:0;list-style:none}
.sc{display:flex;flex-direction:column;gap:.2rem;padding:var(--s4);
  background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  transition:border-color .16s ease}
.sc:hover{border-color:var(--line-mid)}
.sc-value{font-size:2rem;font-weight:700;letter-spacing:-.03em;line-height:1}
.sc-label{margin-top:var(--s2);font-size:.625rem;font-weight:700;letter-spacing:.16em;
  text-transform:uppercase;color:var(--muted)}
.sc-detail{font-size:.8125rem;color:var(--muted)}

/* Log a match. */
.steps{display:grid;gap:var(--s4);margin:0;padding:0;list-style:none}
/* Two columns once there is room for two: the steps are short, and stacking
   them down one side of a wide screen wastes the other side. */
@media (min-width:64rem){
  .steps{grid-template-columns:1fr 1fr;gap:var(--s4) var(--s12)}
  .step:nth-last-child(2){border-bottom:none;padding-bottom:0}
}
.step{display:flex;gap:var(--s4);padding-bottom:var(--s4);
  border-bottom:1px solid var(--line)}
.step:last-child{border-bottom:none;padding-bottom:0}
.step-n{flex:none;font-size:.875rem;font-weight:700;color:var(--ball)}
.step-body{display:flex;flex-direction:column;gap:.2rem;min-width:0}
.step-title{font-weight:700;letter-spacing:-.01em}
.step-text{color:var(--muted);font-size:.9375rem;max-width:60ch}
.commands{display:grid;gap:var(--s3);margin:0;padding:0;list-style:none}
.commands li{display:flex;flex-wrap:wrap;align-items:baseline;gap:var(--s2) var(--s4);
  padding-bottom:var(--s3);border-bottom:1px solid var(--line)}
.commands li:last-child{border-bottom:none;padding-bottom:0}
.commands code{padding:.2rem .45rem;background:var(--raised);border-radius:var(--r-sm);
  font-family:var(--mono);font-size:.8125rem}
.commands span{color:var(--muted);font-size:.875rem}
code{font-family:var(--mono);font-size:.9em}

/* Search: one field that filters live, or asks the server when it must. */
.search{position:relative;display:flex;align-items:center;max-width:22rem;width:100%}
.search-icon{position:absolute;left:.4rem;display:flex;align-items:center;
  justify-content:center;width:30px;height:30px;padding:0;color:var(--text);
  background:transparent;border:0;border-radius:var(--r-sm);cursor:pointer;
  transition:background .16s ease,color .16s ease}
.search-icon:hover{background:var(--raised)}
.search-icon svg{width:17px;height:17px}
.search input{width:100%;padding:.55rem .7rem .55rem 2.5rem;font:inherit;
  font-size:.9375rem;color:var(--text);background:var(--surface);
  border:1px solid var(--line-mid);border-radius:var(--r-btn);
  transition:border-color .16s ease,background .16s ease}
.search input::placeholder{color:var(--muted)}
.search input:focus{border-color:var(--line-strong);background:var(--raised)}
.search input::-webkit-search-cancel-button{filter:invert(1);opacity:.5}
.search-empty{position:absolute;left:0;top:calc(100% + var(--s2));margin:0;
  font-size:.8125rem;color:var(--muted)}
.search+*{margin-top:var(--s4)}

/* Errors. */
.error-page{padding-top:var(--s16)}
.error-page .empty{max-width:640px;margin-inline:auto}
.error-detail{margin:var(--s4) auto 0;max-width:60ch;padding:var(--s3);overflow-x:auto;
  background:var(--surface);border:1px solid var(--line-mid);border-radius:var(--r-sm);
  font-family:var(--mono);font-size:.75rem;color:var(--muted);text-align:left}

/* Navigating: a white thread across the top while the next page is fetched. */
.loading{position:fixed;left:0;top:0;height:2px;width:100%;transform:scaleX(0);
  transform-origin:left;background:var(--ball);z-index:40;opacity:0}
body.is-busy .loading{opacity:1;animation:load 1.4s cubic-bezier(.2,.7,.3,1) forwards}
@keyframes load{0%{transform:scaleX(0)}60%{transform:scaleX(.7)}100%{transform:scaleX(.92)}}
"""

RESPONSIVE = """
@media (max-width:640px){
  .shame-row{grid-template-columns:auto 1fr auto;row-gap:var(--s2)}
  .shame-tallies{grid-column:1/-1;justify-content:flex-start}
  .shame-key-item{grid-template-columns:1fr auto}
  .shame-key-item .d{grid-column:1/-1}
}

@media (min-width:48rem){
  .wrap{padding-inline:var(--s6)}
  .page-head{padding:var(--s16) 0 var(--s8)}
  /* The title keeps the left, the counts take the space it leaves. */
  .head-top{grid-template-columns:minmax(0,1fr) auto;gap:var(--s8)}
  .stat-tiles{display:flex;flex-wrap:wrap;justify-content:flex-end;
    align-items:stretch}
  .stat-tile{min-width:9.5rem}
  .stat-tile .v{font-size:2.25rem}
  .profile{padding:var(--s16) 0 var(--s8)}
  .profile-in{grid-template-columns:auto minmax(0,1fr) auto;gap:var(--s6) var(--s8)}
  .profile-figures{gap:var(--s6) var(--s12)}
  .hero{padding:var(--s16) 0 var(--s12)}
  .hero-stats{display:flex;flex-wrap:wrap;gap:var(--s6) var(--s12)}
  .hero-stats .stat-value{font-size:2rem}
  .featured{padding:var(--s8)}
  .featured-in{grid-template-columns:auto minmax(0,1fr) auto;
    grid-template-areas:"rank who rating" "meta meta meta";
    align-items:center;gap:var(--s6) var(--s8)}
  /* Scoped to the featured panel: these area names exist only in its grid,
     and unscoped they pushed the profile's rating onto a row of its own. */
  .featured-in>.featured-rank{grid-area:rank;align-self:center}
  .featured-in>.featured-body{grid-area:who;min-width:0}
  .featured-in>.featured-rating{grid-area:rating;align-self:center}
  .featured-in>.featured-meta{grid-area:meta;gap:var(--s4) var(--s12)}
  .featured-rating{align-items:flex-end;text-align:right}
  .featured-rating .move{justify-content:flex-end}
  .match-games{gap:.35rem}
  .match-body{position:relative;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);
    gap:var(--s3)}
  .match-body::before{content:"";position:absolute;left:50%;top:-4px;bottom:-4px;
    width:1px;background:repeating-linear-gradient(var(--line-mid) 0 4px,
    transparent 4px 8px)}
  .side{flex-direction:column;align-items:flex-start;justify-content:center;gap:.3rem}
  .side.b{align-items:flex-end;text-align:right}
  /* Only once the sides face each other does the right-hand one read
     inwards; stacked on a phone they both read avatar-first. */
  .side.b .side-names{flex-direction:row-reverse}
  .match-score{padding:0 var(--s2);border-block:0;margin-block:0}
}
@media (min-width:64rem){
  .nav-links{display:flex}
  /* The nav collapses into the menu below this width; the theme picker is
     not navigation and stays at every width. */
  .menu:not(.themes){display:none}
  .row{grid-template-columns:2.6rem minmax(0,14rem) minmax(0,1fr) auto 7.5rem;
    grid-template-areas:"rank who meta form score";gap:var(--s4)}
  .row-meta{padding-left:0}
  .row-form{padding-left:0;justify-content:flex-end}
  .row-score .rating{font-size:1.5rem}
  .matches{grid-template-columns:1fr 1fr}
  .sc-grid{grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}
  .motw .matches,.motw{grid-template-columns:1fr}
  .cmp-matches{grid-template-columns:1fr 1fr}
  .pc-grid{grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}
  .cmp-head{grid-template-columns:repeat(auto-fit,minmax(0,1fr))}
  .page-head+section{margin-top:var(--s6)}
  .footer-in{grid-template-columns:auto 1fr;align-items:start;gap:var(--s12)}
}
"""


def stylesheet():
    """The whole sheet, tokens first."""
    return "".join((tokens.css_root(), BASE, NAV, BUTTONS, HERO, TABS, FEATURED,
                    BOARD, PIECES, MATCHES, PAGES, FOOTER, MOTION, RESPONSIVE))
