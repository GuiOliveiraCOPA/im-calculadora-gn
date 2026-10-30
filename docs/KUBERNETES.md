# Calculadora GN no Kubernetes

Guia para a conversa com os times de arquitetura, rede e segurança, e para o primeiro deploy.
Os modelos estão em `deploy/k8s/` e não foram aplicados em nenhum cluster.

## O que a calculadora precisa

O pod é a imagem Docker rodando. Para ler a Gold, ele faz **uma chamada HTTPS de saída (porta 443)**
ao host do workspace Databricks, igual ao que uma máquina local faz. Não há conexão de entrada
vinda do Databricks nem banco de dados no cluster.

| Item | Valor |
|---|---|
| Destino | Host do workspace (`adb-<id>.<n>.azuredatabricks.net`), porta 443, TLS |
| Leitura | `SELECT` em 2 tabelas: `marketing_prd.marketing_gold.fct_gn_tarifa_vigente_calculadora` e `fct_gn_parametro_vigente_calculadora` (~500 linhas, a cada 30 min) |
| Computação | Um SQL Warehouse (`DATABRICKS_HTTP_PATH`) |
| Estado | Nenhum persistente. Cópia local em `/tmp` (`emptyDir`), refeita a cada carga |
| Réplicas | 2, independentes (cada uma lê a Gold e tem a própria cópia) |

## Checklist com os times

**Segurança / governança (identidade e permissão mínima)**
- [ ] Service principal para a calculadora, um por ambiente (HML e PRD).
- [ ] Permissões: `USE CATALOG` no catálogo, `USE SCHEMA` no `marketing_gold`, `SELECT` só nas 2 tabelas e `CAN USE` no SQL Warehouse.
- [ ] Tipo de credencial. O código usa **OAuth M2M do Databricks** (`DATABRICKS_CLIENT_ID` + secret OAuth gerado no Databricks). Se o padrão da empresa for service principal do **Entra ID** com secret do Azure, ou identidade gerenciada (workload identity), é preciso incluir esse tipo no `calculadora/credenciais.py`. O SDK já suporta, e a mudança fica só nesse arquivo.
- [ ] Onde fica o segredo: Secret do Kubernetes ou Azure Key Vault (CSI driver ou External Secrets), e quem faz a rotação.

**Rede**
- [ ] Egress do cluster até o host do workspace na porta 443 (firewall, NSG, Azure Firewall).
- [ ] Se o workspace usa **Private Link**: DNS do cluster resolvendo `privatelink.azuredatabricks.net` para o IP privado.
- [ ] Se o workspace tem **IP access list**: liberar o IP de saída do cluster.
- [ ] Proxy corporativo: se houver, `HTTPS_PROXY` e `NO_PROXY` no ConfigMap.
- [ ] Exposição do site para os usuários (Ingress/Application Gateway, DNS interno, TLS).

**Plataforma**
- [ ] Registro da imagem (ACR) e pipeline de build (`docker build --target teste .` roda os testes).
- [ ] Namespace por ambiente, recursos (`requests`/`limits`) e política de rede.

## Como validar a rede antes do deploy

Com o ConfigMap e o Secret aplicados no namespace, rode o diagnóstico num pod temporário com a
mesma imagem:

```bash
kubectl run gn-teste --rm -it --restart=Never --image=<registro>/calculadora-gn:<versao> \
  --overrides='{"spec":{"containers":[{"name":"gn-teste","image":"<registro>/calculadora-gn:<versao>",
    "command":["python","scripts/testar_conexao.py","--tabela-proibida","marketing_prd.marketing_gold.dim_gn_uf"],
    "envFrom":[{"configMapRef":{"name":"calculadora-gn-config"}},{"secretRef":{"name":"calculadora-gn-credenciais"}}]}]}}'
```

O script testa, nesta ordem: configuração, DNS, TCP 443, autenticação + warehouse (`SELECT 1`),
leitura das 2 tabelas, validação do contrato e acesso mínimo (a leitura de outra tabela **tem de
ser negada**). Ele para na primeira camada que falhar e diz o que verificar. Código de saída: 2 DNS,
3 rede, 4 autenticação/warehouse, 5 permissão nas tabelas, 7 permissão maior que a necessária.

## Deploy

```bash
kubectl apply -f deploy/k8s/configmap.yaml     # depois de preencher host e http_path
kubectl apply -f <secret preenchido, fora do git>
kubectl apply -f deploy/k8s/deployment.yaml -f deploy/k8s/service.yaml
kubectl rollout status deploy/calculadora-gn
kubectl port-forward svc/calculadora-gn 8080:80   # http://127.0.0.1:8080/saude
```

- **Liveness (`/saude`)** não consulta o Databricks: uma queda dele não reinicia os pods.
- **Readiness (`/saude/pronto`)** só fica verde com base válida em memória. Na primeira subida, com o
  warehouse desligado, isso pode levar alguns minutos. Com `maxUnavailable: 0`, a versão anterior
  continua atendendo até a nova estar pronta.
- O pod roda com `readOnlyRootFilesystem`, sem root e sem capabilities. A única escrita é em `/tmp`.

## Operação

| Sintoma | Onde olhar |
|---|---|
| `/saude` com `status = degradado` e `origem = cache_local` | Databricks inacessível. Veja `ultimo_erro` no `/saude` e o log do pod; rode o `testar_conexao.py` |
| `ultimo_erro` com `inválida` | A Gold publicou algo fora do contrato. A calculadora segue com a base anterior; avise o time do dbt |
| Aviso "base não é atualizada desde" na tela | Mais de 72 h sem carga válida: Job da ingestão/dbt ou conexão |
| Pod não fica pronto | Sem base e sem cópia: primeira carga falhando (credencial, rede ou permissão) |
