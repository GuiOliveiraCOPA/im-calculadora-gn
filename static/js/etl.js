// Tela interna do ETL: acompanha a execução em andamento e mostra os logs na própria página.
(function () {
  const painel = document.getElementById("painelEtl");
  if (!painel) return;
  const urlStatus = painel.dataset.status;
  const urlLog = (nome) => painel.dataset.log.replace("__NOME__", encodeURIComponent(nome));

  // Lê o log a partir do byte `desde` e acrescenta no <pre>.
  function acompanharLog(nome, pre, continuar) {
    let desde = 0;
    pre.textContent = "";
    async function ler() {
      try {
        const resposta = await fetch(`${urlLog(nome)}?desde=${desde}`, { cache: "no-store" });
        if (!resposta.ok) throw new Error(resposta.status);
        const dados = await resposta.json();
        const noFim = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
        if (dados.desde < desde) pre.textContent = "";
        pre.textContent += dados.texto;
        desde = dados.tamanho;
        if (noFim) pre.scrollTop = pre.scrollHeight;
      } catch (erro) {
        pre.textContent += `\n[não foi possível ler o log: ${erro.message}]`;
        return;
      }
      if (continuar()) setTimeout(ler, 2000);
    }
    ler();
  }

  // Execução em andamento: log ao vivo e recarga da página no fim.
  const emExecucao = painel.dataset.emExecucao;
  if (emExecucao) {
    let rodando = true;
    acompanharLog(emExecucao, document.getElementById("logAtual"), () => rodando);
    const etapa = document.getElementById("etapaAtual");
    const ufs = document.getElementById("ufsAtual");
    const classe = (s) => (s === "ok" ? "ok" : s === "rodando" ? "rodando" : "falha");
    async function verificar() {
      try {
        const status = await (await fetch(urlStatus, { cache: "no-store" })).json();
        if (!status.em_execucao) {
          rodando = false;
          setTimeout(() => window.location.reload(), 2500);
          return;
        }
        etapa.textContent = status.em_execucao.etapa;
        ufs.replaceChildren(...status.em_execucao.ufs.map((item) => {
          const li = document.createElement("li");
          li.className = `etl-uf-${classe(item.status)}`;
          li.append(item.uf + " ");
          const small = document.createElement("small");
          small.textContent = item.status;
          li.append(small);
          return li;
        }));
      } catch (_) { /* tenta de novo na próxima rodada */ }
      setTimeout(verificar, 4000);
    }
    setTimeout(verificar, 4000);
  }

  // Links "ver": abrem o log na página em vez de baixar.
  const visor = document.getElementById("visorLog");
  document.querySelectorAll("[data-ver-log]").forEach((link) => {
    link.addEventListener("click", (evento) => {
      evento.preventDefault();
      const nome = link.dataset.verLog;
      visor.hidden = false;
      document.getElementById("visorTitulo").textContent = nome;
      acompanharLog(nome, document.getElementById("visorTexto"), () => nome === emExecucao);
      visor.scrollIntoView({ behavior: "smooth" });
    });
  });
})();
