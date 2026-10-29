// Integração da tela com o servidor Python.
// Todo cálculo, filtro e formatação acontece em /api/calcular (Flask);
// aqui só enviamos as premissas e aplicamos a resposta na tela.
(() => {
  const form = document.getElementById("calculatorForm");
  if (!form) return;

  const selects = {
    uf: document.getElementById("ufSelect"),
    segmento_copa: document.getElementById("segmentoCopaSelect"),
    concessionaria: document.getElementById("concessionariaSelect"),
    segmento: document.getElementById("segmentoSelect"),
  };

  let ultimaRequisicao = 0;
  let controlador = null;
  let espera = null;

  function preencherSelect(select, { opcoes, selecionado }) {
    select.replaceChildren(...opcoes.map((valor) => new Option(valor, valor, false, valor === selecionado)));
    select.value = selecionado;
  }

  async function atualizar() {
    const parametros = new URLSearchParams(new FormData(form));
    const numero = ++ultimaRequisicao;
    controlador?.abort();
    controlador = new AbortController();

    try {
      const resposta = await fetch(`${form.dataset.api}?${parametros}`, { signal: controlador.signal });
      if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
      const dados = await resposta.json();
      if (numero !== ultimaRequisicao) return; // chegou uma resposta mais nova

      Object.entries(selects).forEach(([nome, select]) => preencherSelect(select, dados.filtros[nome]));
      document.getElementById("resultados").outerHTML = dados.html;
      history.replaceState(null, "", `?${new URLSearchParams(new FormData(form))}`);
    } catch (erro) {
      if (erro.name === "AbortError") return;
      const resumo = document.getElementById("resultadoResumoCopia");
      if (resumo) resumo.textContent = "Não foi possível calcular agora. Verifique se o servidor da calculadora está em execução.";
      console.error(erro);
    }
  }

  form.addEventListener("change", (evento) => {
    if (evento.target.id === "consumoInput") return; // tratado no "input"
    atualizar();
  });
  form.addEventListener("input", (evento) => {
    if (evento.target.id !== "consumoInput") return;
    clearTimeout(espera);
    espera = setTimeout(atualizar, 150);
  });
  form.addEventListener("submit", (evento) => {
    evento.preventDefault();
    atualizar();
  });
})();
