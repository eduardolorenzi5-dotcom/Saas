document.addEventListener('DOMContentLoaded', () => {
  const inp = document.getElementById('inp-data');
  if (inp) inp.valueAsDate = new Date();
});

async function addGasto() {
  const desc = document.getElementById('inp-desc').value.trim();
  const val  = document.getElementById('inp-val').value;
  const cat  = document.getElementById('inp-cat').value;
  const data = document.getElementById('inp-data').value;
  if (!desc || !val || parseFloat(val) <= 0) { alert('Preencha descrição e valor.'); return; }
  const res = await fetch('/api/gastos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ descricao: desc, valor: parseFloat(val), categoria: cat, data })
  });
  if (res.ok) location.reload();
}

async function delGasto(id) {
  if (!confirm('Excluir este gasto?')) return;
  const res = await fetch(`/api/gastos/${id}`, { method: 'DELETE' });
  if (res.ok) document.getElementById(`g-${id}`)?.remove();
}
