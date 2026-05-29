// ── MÁSCARA DE MOEDA BRASILEIRA ───────────────────────────────────────────────
function mascaraMoeda(el) {
  let v = el.value.replace(/\D/g, '');       // só dígitos
  if (!v) { el.value = ''; return; }
  v = v.replace(/^0+/, '') || '0';            // remove zeros à esquerda
  v = v.padStart(3, '0');                     // mínimo 3 dígitos (garante centavos)
  const centavos = v.slice(-2);
  let reais = v.slice(0, -2).replace(/^0+/, '') || '0';
  reais = reais.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  el.value = reais + ',' + centavos;
}

function parseMoeda(str) {
  if (!str) return 0;
  // "2.500,99" → 2500.99
  return parseFloat(String(str).replace(/\./g, '').replace(',', '.')) || 0;
}

function formatarMoeda(numero) {
  // 2500.9 → "2.500,90"
  if (numero === null || numero === undefined || isNaN(numero)) return '0,00';
  const str = parseFloat(numero).toFixed(2);
  const [reais, centavos] = str.split('.');
  return reais.replace(/\B(?=(\d{3})+(?!\d))/g, '.') + ',' + centavos;
}

// Inicializa inputs com classe "moeda-br" que têm data-valor definido
function initMoedaInputs() {
  document.querySelectorAll('input.moeda-br[data-valor]').forEach(el => {
    const raw = parseFloat(el.dataset.valor);
    el.value = isNaN(raw) ? '' : formatarMoeda(raw);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const inp = document.getElementById('inp-data');
  if (inp) inp.valueAsDate = new Date();
  const txData = document.getElementById('tx-data');
  if (txData) txData.valueAsDate = new Date();
  const parcData = document.getElementById('parc-data');
  if (parcData) parcData.valueAsDate = new Date();

  initMoedaInputs();
});

// ── GASTOS ────────────────────────────────────────────────────────────────────
async function addGasto() {
  const desc = document.getElementById('inp-desc').value.trim();
  const val  = parseMoeda(document.getElementById('inp-val').value);
  const cat  = document.getElementById('inp-cat').value;
  const data = document.getElementById('inp-data').value;
  const contaEl = document.getElementById('inp-conta');
  const conta_id = contaEl ? (parseInt(contaEl.value) || null) : null;
  if (!desc || val <= 0) { alert('Preencha descrição e valor.'); return; }
  const res = await fetch('/api/gastos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ descricao: desc, valor: val, categoria: cat, data, conta_id })
  });
  if (res.ok) location.reload();
}

async function delGasto(id) {
  if (!confirm('Excluir este gasto?')) return;
  const res = await fetch(`/api/gastos/${id}`, { method: 'DELETE' });
  if (res.ok) document.getElementById(`g-${id}`)?.remove();
}

async function limparTudo() {
  if (!confirm('Apagar TODOS os gastos deste mês? Esta ação não pode ser desfeita.')) return;
  const res = await fetch('/api/gastos/mes', { method: 'DELETE' });
  if (res.ok) location.reload();
}
