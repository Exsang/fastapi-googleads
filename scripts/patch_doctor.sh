cat > .chatgpt_patch.diff <<'DIFF'
diff --git a/scripts/patch_doctor.sh b/scripts/patch_doctor.sh
new file mode 100755
index 0000000..1111111
--- /dev/null
+++ b/scripts/patch_doctor.sh
@@ -0,0 +52 @@
+#!/usr/bin/env bash
+set -euo pipefail
+IN="${1:-.chatgpt_patch.diff}"
+OUT="${IN%.diff}.clean.diff"
+
+# Strip markdown code fences and normalize CRLF
+awk 'BEGIN{inblk=0} /^```/{inblk=!inblk; next} {print}' "$IN" > "$OUT"
+sed -i 's/\r$//' "$OUT"
+
+# Try different -p strip levels to match headers
+for p in "" "-p0" "-p1"; do
+  if git apply --check $p "$OUT" 2>/dev/null; then
+    echo "[patch_doctor] OK with $p; applying…"
+    git apply $p "$OUT"
+    echo "Applied. Next: git add -A && git commit -m \"chore: apply ChatGPT patch\""
+    exit 0
+  fi
+done
+
+echo "[patch_doctor] Failed. Showing first 30 lines for inspection:"
+nl -ba "$OUT" | sed -n '1,30p'
+exit 1
DIFF
