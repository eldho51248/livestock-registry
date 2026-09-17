# Livestock Registry — Staff Portal UI image.
#
# Thin extension of the registry-platform staff-ui image. The Next.js app itself
# is used unchanged; this image only overrides what the platform bakes into its
# build output rather than exposing through configuration.
#
# WHY THIS IMAGE EXISTS
# Branding reaches the UI two ways. Colours, logo, favicon and the dashboard
# illustration are THEME DATA — seeded into the registry DB, editable at runtime
# under Configuration -> Theme. The page background is NOT: the dashboard paints
# it with a compiled Tailwind class,
#   bg-primary-first bg-[url('/images/common/bg_pattern.png')]
# which tiles a small tile at its natural size. A photograph needs
# background-size: cover, and there is no class or theme key for that — so the
# rule has to be overridden in the compiled stylesheet.
#
# The same constraint is why the Dashboard header button is added here: the portal
# is published as a finished build, so a new control cannot be contributed as a
# component or a route. See the patch step at the foot of this file.
#
# Build context = repo root (matching the other docker/*/Dockerfile images).
ARG RP_VERSION=0.0.0-develop.296
FROM openg2p/openg2p-registry-staff-ui:${RP_VERSION}

# Browser-facing origin of the dashboard service, compiled into the client bundle
# by patch-dashboard-nav.js below — so changing it needs a rebuild, not a restart.
ARG DASHBOARD_URL=http://dashboard.localtest.me:3001
ARG DASHBOARD_LABEL=Dashboard

COPY --chown=nextjs:nodejs docker/staff-ui/assets/livestock_bg.jpg /app/public/images/common/livestock_bg.jpg

# Repoint the dashboard background at the photo and make it cover the viewport.
#
# The override is appended to whichever compiled stylesheet already references
# bg_pattern, so it lands after the original rule and wins on cascade order at
# equal specificity. The selector matches on the Tailwind arbitrary-value class
# name itself — that class literally contains "bg_pattern", and it is the only
# thing on the page that does.
#
# This is coupled to someone else's build output, and the failure is SILENT: a
# platform bump that renames the class or drops the rule would leave the
# override matching nothing and the stock tile back. Assert the contract so a
# bump fails the build instead of the design review.
# The stylesheet is served `Cache-Control: immutable, max-age=1y` under a
# content-hashed name. Appending to it post-build changes the bytes but NOT the
# URL, so every browser that has already loaded the page keeps the stale CSS
# forever — a hard refresh does not necessarily re-fetch an immutable asset.
# So the file is also RENAMED and every reference in the build output rewritten,
# which is what makes the new rule actually reach the browser.
#
# overrides.css rides on the same step: it targets the possible-duplicate match
# cards (see the comments in the file) and is appended to the same global
# stylesheet, so it is covered by the same rename. Its selectors are asserted
# the same way as bg_pattern.
COPY --chown=nextjs:nodejs docker/staff-ui/assets/overrides.css /tmp/overrides.css
RUN set -eu; \
    css="$(find /app/.next/static -name '*.css' -exec grep -l 'bg_pattern' {} + 2>/dev/null || true)"; \
    if [ -z "$css" ]; then \
      echo "FATAL: no compiled stylesheet references bg_pattern — override would be dead"; exit 1; \
    fi; \
    for f in $css; do \
      printf '%s' \
        '[class*="bg_pattern"]{' \
        'background-image:linear-gradient(rgba(0,0,0,.30),rgba(0,0,0,.30)),url("/images/common/livestock_bg.jpg")!important;' \
        'background-size:cover!important;' \
        'background-repeat:no-repeat!important;' \
        'background-position:center center!important;' \
        'background-attachment:fixed!important;' \
        '}' >> "$f"; \
      for cls in ':grid-cols-3' '.pl-10' '.border-l' '.truncate'; do \
        grep -qF -- "$cls" "$f" || { echo "FATAL: compiled stylesheet no longer has $cls — overrides.css would be dead"; exit 1; }; \
      done; \
      printf '\n' >> "$f"; cat /tmp/overrides.css >> "$f"; \
      old="$(basename "$f" .css)"; new="${old}ls$(md5sum "$f" | cut -c1-6)"; \
      grep -rl "$old" /app/.next 2>/dev/null | while read -r ref; do \
        sed -i "s/${old}/${new}/g" "$ref"; \
      done; \
      mv "$(dirname "$f")/${old}.css" "$(dirname "$f")/${new}.css"; \
      echo "background override appended; stylesheet ${old}.css -> ${new}.css (busts the immutable cache)"; \
    done

# ── Add the Dashboard header button ─────────────────────────────────────────
# Puts a Dashboard control immediately left of Configuration, pointing at the
# dashboard-ui service. The dashboard is a separate origin — the portal cannot be
# extended with new routes — so the target is baked in here rather than resolved
# as a portal route. Runs after the stylesheet rename above, which rewrites
# references by CSS basename and so is unaffected by the chunk renames this does.
COPY --chown=nextjs:nodejs docker/staff-ui/assets/patch-dashboard-nav.js /tmp/patch-dashboard-nav.js
RUN DASHBOARD_URL="${DASHBOARD_URL}" DASHBOARD_LABEL="${DASHBOARD_LABEL}" \
    node /tmp/patch-dashboard-nav.js

# ── Enable sibling-table / widget-autofill / age-from-date data sources ────
# The pinned platform's widget runtime has no code for the `sibling-table`,
# `widget-autofill` or `widget-age-from-date` data-source keys this registry's
# section UI schemas declare (Livestock Ear Tag pickers, the Species/Age
# autofill that follows one, and the Age field that derives itself from Date
# of Birth). Without this, those dropdowns render empty and Age never
# populates. See the patch file's header for the full mechanism.
COPY --chown=nextjs:nodejs docker/staff-ui/assets/patch-sibling-table.js /tmp/patch-sibling-table.js
RUN node /tmp/patch-sibling-table.js

# ── Rename the attribute-value "Sort Order" field label to "Display Order" ──
# Configuration -> Attributes (and Configuration -> Registry -> Languages,
# which shares the same i18n key) label the g2p_attribute_values.sort_order
# field "Sort Order". The value is opaque as a name for what the field
# actually does — set the position a value takes in its attribute's list —
# so it is relabelled "Display Order" for clarity.
#
# The string is translated i18n content, not a component prop, so unlike the
# Dashboard button above this is a plain text substitution: every compiled
# bundle holding the literal key/value pair `"sort_order":"Sort Order"` gets
# it swapped for `"sort_order":"Display Order"`. Asserts at least one match so
# a base-image change (translations restructured, key renamed) fails the
# build instead of silently leaving the old label in place.
RUN set -eu; \
    files="$(grep -rl '"sort_order":"Sort Order"' /app/.next 2>/dev/null || true)"; \
    if [ -z "$files" ]; then \
      echo "FATAL: no compiled bundle has the sort_order label — rename would be dead"; exit 1; \
    fi; \
    for f in $files; do \
      sed -i 's/"sort_order":"Sort Order"/"sort_order":"Display Order"/g' "$f"; \
      echo "  patched ${f#/app/.next/}"; \
    done; \
    case "$files" in \
      */static/*) \
        for f in $files; do \
          case "$f" in \
            */static/*) \
              old="$(basename "$f")"; ext="${old##*.}"; base="${old%.*}"; new="${base}.do.${ext}"; \
              grep -rl "$old" /app/.next 2>/dev/null | while read -r ref; do \
                sed -i "s/${old}/${new}/g" "$ref"; \
              done; \
              mv "$(dirname "$f")/${old}" "$(dirname "$f")/${new}"; \
              echo "  renamed ${old} -> ${new} (busts the immutable cache)"; \
              ;; \
          esac; \
        done; \
        ;; \
    esac; \
    echo "sort_order label renamed to 'Display Order'"
