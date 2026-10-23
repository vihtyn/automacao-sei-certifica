# Automação SEI 5.0 - Diagnóstico e Auditoria de Processos CERTIFICA

Robô desenvolvido para o setor **ORCN** da **ANATEL**, destinado ao mapeamento, triagem e controle de processos gerados automaticamente pelo sistema **CERTIFICA** no SEI (Sistema Eletrônico de Informações).

---

## 📋 Contexto do Projeto

O sistema interno CERTIFICA gera processos de homologação de produtos no SEI. Devido a integrações do sistema, alguns processos são criados vazios (sem nenhum documento na árvore processual).

Este robô automatiza a varredura da caixa de **Gerados** da unidade, inspeciona a árvore de cada processo do CERTIFICA e separa:
* **Processos Vazios:** Candidatos para futura exclusão/cancelamento quando a área técnica autorizar.
* **Processos com Conteúdo:** Processos legítimos que contêm requerimentos, despachos ou certificados, direcionados para o trabalho dos analistas.

> **Importante:** Atualmente o robô opera em modo de **Auditoria e Diagnóstico (não exclui nada)**, gerando relatórios com carimbo de data e hora para acompanhamento da chefia e equipe de desenvolvimento.

---

## 🛠️ Tecnologias Utilizadas

* **Python 3.12+**
* **Playwright:** Automação web moderna com suporte nativo ao Google Chrome corporativo e `iframes` do SEI.
* **Pandas & OpenPyXL:** Manipulação de dados e geração de planilhas Excel formatadas.

---

## 📁 Estrutura do Repositório

```text
Automacao SEI Certifica/
│
├── saidas/                                         # Pasta de relatórios (gerada automaticamente)
│   ├── .gitkeep                                   # Mantém a pasta versionada
│   ├── relatorio_certifica_YYYY-MM-DD_HHhMM.xlsx  # Relatório completo em abas
│   ├── nups_vazios_YYYY-MM-DD_HHhMM.txt          # Lista simples de NUPs vazios (um por linha)
│   └── historico_consolidado.csv                 # Banco cumulativo dia a dia
│
├── robo_sei_certifica.py                           # Script principal da automação
├── requirements.txt                               # Dependências Python do projeto
├── .gitignore                                     # Arquivos e relatórios ignorados no Git
└── README.md                                      # Documentação do projeto
```

---

## 🚀 Como Executar

### 1. Pré-requisitos
Certifique-se de que as dependências estejam instaladas:

```powershell
pip install -r requirements.txt
```

### 2. Executando o Robô
No terminal, execute:

```powershell
python robo_sei_certifica.py
```

### 3. Passo a Passo Durante a Execução:
1. Uma janela do **Google Chrome** abrirá na tela de login do SEI.
2. Faça seu login com suas credenciais normais (Azure AD / SSO Anatel / Rede).
3. Selecione a unidade desejada (ex: `ORCN`).
4. Na tela inicial de **Controle de Processos**, certifique-se de que a coluna **Gerados** está visível.
5. Volte ao terminal e aperte `ENTER`.
6. Escolha a quantidade de processos que deseja analisar (ex: `20`, `50`, ou `T` para todos).
7. O robô realizará a leitura e salvará automaticamente os relatórios na pasta `saidas/`.

---

## 📊 Relatórios Gerados

A cada execução, o robô salva na pasta `saidas/`:

1. **Planilha Excel (`.xlsx`):**
   * **Aba 1 (`Candidatos_Exclusao`):** Lista dos processos vazios.
   * **Aba 2 (`Com_Conteudo`):** Processos que possuem documentos reais.
   * **Aba 3 (`Geral_Auditados`):** Todos os processos verificados com data/hora da auditoria.
2. **Arquivo de Texto (`.txt`):**
   * Apenas os números dos processos (NUPs) vazios, facilitando o envio rápido para a chefia ou equipe técnica.
3. **Histórico Geral (`.csv`):**
   * Arquivo cumulativo que guarda o histórico de todas as rodadas realizadas ao longo do tempo.

---

## 🔒 Segurança e Boas Práticas

* **Sem Credenciais no Código:** Nenhuma senha ou token de acesso é salvo no robô. A autenticação é realizada diretamente pelo usuário no navegador.
* **Dry-Run por Padrão:** O código não executa ações destrutivas sem autorização explícita.
* **Proteção de Interrupção:** Se a execução for interrompida com `Ctrl + C`, os dados já analisados até aquele momento são salvos com segurança.
