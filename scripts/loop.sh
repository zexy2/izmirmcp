#!/usr/bin/env zsh
# Pass tabanlı döngü: her tur temiz context'le tek bir pass'i bitirir.
#
# Kullanım:
#   ./scripts/loop.sh              # sıradaki ilk bekleyen pass'i çalıştır
#   ./scripts/loop.sh 2            # en fazla 2 pass çalıştır
#   ./scripts/loop.sh --pass P2    # sadece belirtilen pass
#   ./scripts/loop.sh --dry-run    # ne yapacağını yaz, çalıştırma
#
# Durum PROGRESS.md ve git log'da yaşar; her tur bunları okuyarak başlar.
set -u

cd "${0:A:h}/.." || exit 1

MODEL="${IZMIR_LOOP_MODEL:-river/deepseek-ai/DeepSeek-V4.1-Flash-1017}"
MAX_PASSES=1
DRY_RUN=0
ONLY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --pass) ONLY="$2"; shift 2 ;;
    --all) MAX_PASSES=99; shift ;;
    [0-9]*) MAX_PASSES="$1"; shift ;;
    *) echo "Bilinmeyen argüman: $1"; exit 2 ;;
  esac
done

PASSES=(
  "P1|Çok operatörlü ulaşım aksaklıkları: Metro, İZBAN ve İZDENİZ için makine-okunur duyuru/aksaklık uçlarını canlı doğrula. Erişilebilen her operatör izmir_transport_disruptions içine ayrı sources[] kaydıyla eklensin; erişilemeyen operatör unavailable dönsün ve 'sorun yok' sayılmasın. Uç yoksa kanıtla PROGRESS.md bilinçli boşluklara yaz."
  "P2|Paketleme: Dockerfile + .dockerignore, server.json (MCP registry manifesti), .github/workflows/ci.yml (pytest + smoke + import), CHANGELOG.md. Image'da .data/ ve .venv/ olmamalı; GTFS deposu çalışma anında yeniden kurulabilmeli."
  "P3|Dokümantasyon: docs/response-contract.md, docs/tool-reference.md, docs/deployment.md, docs/sources.md, docs/monitoring.md. Her doküman gerçek koddan türetilsin; uydurma davranış yazılmasın."
  "P4|Sözleşme ve güvenlik testleri: tüm araçlar için zarf alanı conformance testi, keşif yüzeyi (tools/resources/prompts) şema testi, auth bypass / origin bypass / büyük gövde / XFF spoofing güvenlik testleri."
)

run_pass() {
  local spec="$1" label="${1%%|*}" task="${1#*|}"
  echo "──────────── $label ────────────"
  echo "$task"
  echo

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "(dry-run: çalıştırılmadı)"
    return 0
  fi

  opencode run --model "$MODEL" "$(cat <<EOF
Mission: İzmir MCP, /Users/mac/Desktop/projeler/02-Web-Mobil/izmirmcp.
Upstream parity hedefi — İzmir'de gerçek veri karşılığı olan her şeyi eşdeğer
kalitede yap; kaynak yoksa yapma, kanıtla yaz. Veri uydurma.

BU TUR TEK İŞ: $label — $task

Başlamadan önce:
1. AGENTS.md oku (değişmez kurallar, doğrulama komutları, mimari sınırlar).
2. PROGRESS.md oku — nerede kaldığımızı ve bilinçli boşlukları gör.
3. git log -3 ile son commit'leri gör.

Kurallar:
- TDD: önce başarısız test, sonra kod.
- Zarf sözleşmesini ve hata taksonomisini koru.
- Bitirmeden önce çalıştır: .venv/bin/python -m pytest -q
  ve .venv/bin/python scripts/smoke_live.py
- README (araç tablosu + Sınırlar) ve PROGRESS.md'yi gerçeğe göre güncelle.
- Yeni dış uç bağladıysan canlı doğrula ve reports/ altına kanıt yaz.
- Bitince tek odaklı git commit at (push yok).
- Bu pass dışındaki işlere girme.

Rapor: ne yaptın, ne doğruladın, ne yapmadın ve neden.
EOF
)"
}

started=0
for spec in "${PASSES[@]}"; do
  label="${spec%%|*}"
  if [ -n "$ONLY" ] && [ "$label" != "$ONLY" ]; then
    continue
  fi
  if [ "$started" -ge "$MAX_PASSES" ]; then
    break
  fi
  run_pass "$spec" || { echo "!! $label başarısız"; exit 1; }
  started=$((started + 1))
done

if [ "$started" -eq 0 ]; then
  echo "Çalıştırılacak pass bulunamadı. --pass P1 gibi bir hedef verin."
  exit 1
fi

echo
echo "Bitti: $started pass. PROGRESS.md güncel mi kontrol edin."
