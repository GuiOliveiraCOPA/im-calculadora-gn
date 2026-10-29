// Executa o app.js ORIGINAL (5_Calculadora_Final) em Node com um DOM simulado
// e grava o que ele exibe para uma bateria de cenários. O teste Python compara
// essas saídas com as da versão Flask.
//
// Uso: node executar_app_js.js <tarifas.js> <app.js> <saida.json>
const fs = require("fs");
const vm = require("vm");

const [tarifasJs, appJs, saida] = process.argv.slice(2);

function elemento(id) {
  return { id, value: "", textContent: "", innerHTML: "", hidden: false, addEventListener() {} };
}

function select(id) {
  const el = elemento(id);
  let opcoes = [];
  let valor = null;
  Object.defineProperty(el, "innerHTML", {
    get: () => "",
    set: () => { opcoes = []; valor = null; },
  });
  Object.defineProperty(el, "value", {
    // Como no navegador: sem escolha explícita, vale a primeira opção.
    get: () => (valor !== null ? valor : opcoes.length ? opcoes[0].value : ""),
    set: (v) => { valor = opcoes.some((o) => o.value === v) ? v : ""; },
  });
  el.appendChild = (opcao) => opcoes.push(opcao);
  el.opcoes = () => opcoes.map((o) => o.value);
  el.forcar = (v) => { opcoes = [{ value: v }]; valor = v; }; // valor "anterior" arbitrário
  return el;
}

const ids = [
  "consumoInput", "volumeInputLabel", "faturaLiquida", "faturaBruta", "volumeGn", "volumeGlp",
  "semCreditoImpostos", "semCreditoImpostosCopia", "resultadoResumo", "comparisonCreditoPanel",
  "resultadoResumoCopia", "faixasResumo", "cenariosBody", "cenariosBodyCopia", "faixasBody",
  "faixasFoot", "faixasMobile", "pisCofinsHeader", "icmsHeader", "termoFixoHeader",
];
const els = Object.fromEntries(ids.map((id) => [id, elemento(id)]));
["ufSelect", "segmentoCopaSelect", "concessionariaSelect", "segmentoSelect"].forEach((id) => (els[id] = select(id)));
// semCreditoImpostos não existe no index.html atual
delete els.semCreditoImpostos;
delete els.semCreditoImpostosCopia;
els.consumoInput.value = "5000";

let tipoEntrada = "glp";
const document = {
  getElementById: (id) => els[id] || null,
  createElement: () => ({ value: "", textContent: "" }),
  querySelector: () => ({ value: tipoEntrada }),
  querySelectorAll: () => [],
};

const contexto = vm.createContext({ window: {}, document, console, Intl });
vm.runInContext(fs.readFileSync(tarifasJs, "utf8").replace(/^﻿/, ""), contexto);
vm.runInContext(fs.readFileSync(appJs, "utf8").replace(/^﻿/, ""), contexto);

const records = contexto.window.TARIFAS_GN.records;
const unicos = (lista) => [...new Set(lista)];

// ---------------------------------------------------------------- filtros
const ufs = unicos(records.map((r) => r.uf)).concat(["", "XX"]);
const segmentosCopa = unicos(records.map((r) => r.segmento_copa)).concat([""]);
const concessionarias = unicos(records.map((r) => r.concessionaria)).concat([""]);
const filtros = [];
for (const uf of ufs) {
  for (const segmentoCopa of segmentosCopa) {
    for (const concessionaria of concessionarias) {
      els.ufSelect.forcar(uf);
      els.segmentoCopaSelect.forcar(segmentoCopa);
      els.concessionariaSelect.forcar(concessionaria);
      els.segmentoSelect.forcar("");
      vm.runInContext("updateFilters()", contexto);
      filtros.push({
        entrada: { uf, segmento_copa: segmentoCopa, concessionaria },
        saida: Object.fromEntries(
          [["uf", "ufSelect"], ["segmento_copa", "segmentoCopaSelect"], ["concessionaria", "concessionariaSelect"], ["segmento", "segmentoSelect"]]
            .map(([nome, id]) => [nome, { opcoes: els[id].opcoes(), selecionado: els[id].value }])
        ),
      });
    }
  }
}

// ---------------------------------------------------------------- cálculos
const combinacoes = unicos(records.map((r) => JSON.stringify([r.uf, r.segmento_copa, r.concessionaria, r.segmento]))).map(JSON.parse);
const volumes = ["", "0", "-10", "0.01", "1", "10", "99.99", "100", "500", "500.005", "1000", "2000.01", "5000", "12345.67", "50000", "250000", "1000000", "25000000", "1e10"];
const calculos = [];
for (const [uf, segmentoCopa, concessionaria, segmento] of combinacoes) {
  for (const tipo of ["glp", "gn"]) {
    for (const volume of volumes) {
      els.ufSelect.forcar(uf);
      els.segmentoCopaSelect.forcar(segmentoCopa);
      els.concessionariaSelect.forcar(concessionaria);
      els.segmentoSelect.forcar(segmento);
      vm.runInContext("updateFilters()", contexto);
      tipoEntrada = tipo;
      els.consumoInput.value = volume;
      vm.runInContext("renderCalculation()", contexto);
      calculos.push({
        entrada: { uf, segmento_copa: segmentoCopa, concessionaria, segmento, tipo_entrada: tipo, volume },
        texto: Object.fromEntries(
          ["volumeGlp", "volumeGn", "faturaLiquida", "faturaBruta", "resultadoResumo", "resultadoResumoCopia", "faixasResumo", "pisCofinsHeader", "icmsHeader"]
            .map((id) => [id, els[id].textContent])
        ),
        html: Object.fromEntries(
          ["cenariosBody", "cenariosBodyCopia", "faixasBody", "faixasFoot", "faixasMobile"].map((id) => [id, els[id].innerHTML])
        ),
        oculto: { comparisonCreditoPanel: els.comparisonCreditoPanel.hidden, termoFixoHeader: els.termoFixoHeader.hidden },
      });
    }
  }
}

fs.writeFileSync(saida, JSON.stringify({ filtros, calculos }), "utf8");
console.log(`filtros=${filtros.length} calculos=${calculos.length}`);
