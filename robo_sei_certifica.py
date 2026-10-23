"""
Robô de Automação SEI 5.0.5 - Módulo de Auditoria e Diagnóstico de Processos CERTIFICA
Desenvolvido para ANATEL / Setor ORCN

Modo: AUDITORIA / SALVAMENTO DE RELATÓRIOS
- NÃO exclui nenhum processo.
- Mapeia processos vazios do sistema CERTIFICA.
- Salva relatórios detalhados com data/hora na pasta 'saidas/'.
- Mantém histórico cumulativo das execuções diárias.
"""

import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin
import pandas as pd
from playwright.sync_api import sync_playwright

# ==========================================
# CONFIGURAÇÕES
# ==========================================
URL_SEI = "https://sei.anatel.gov.br"
PASTA_SAIDAS = "saidas"
ARQUIVO_HISTORICO = os.path.join(PASTA_SAIDAS, "historico_consolidado.csv")


def garantir_diretorios():
    """Garante que a pasta de saídas existe."""
    os.makedirs(PASTA_SAIDAS, exist_ok=True)


def extrair_info_tooltip(link_element):
    """Extrai informações de tooltip do link do processo."""
    try:
        title = link_element.get_attribute("title") or ""
        data_title = (link_element.get_attribute("data-bs-original-title") or 
                      link_element.get_attribute("data-original-title") or "")
        onmouseover = link_element.get_attribute("onmouseover") or ""
        aria_label = link_element.get_attribute("aria-label") or ""
        
        texto_completo = f"{title} {data_title} {onmouseover} {aria_label}".strip()
        return texto_completo
    except Exception:
        return ""


def verificar_se_eh_certifica(texto_info):
    """Verifica se o processo pertence ao sistema CERTIFICA."""
    return "CERTIFICA" in texto_info.upper()


def obter_pagina_ativa(context):
    """Retorna a última aba aberta pelo usuário."""
    paginas = context.pages
    return paginas[-1] if paginas else None


def aguardar_estabilizacao(page):
    """Aguarda a página terminar carregamentos pendentes."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    time.sleep(1.5)


def analisar_arvore_processo(page_processo):
    """
    Analisa a árvore de documentos do processo aberto no SEI 5.0.
    Retorna: (esta_vazio: bool, qtd_documentos: int, documentos: list)
    """
    try:
        time.sleep(2.0)  # Tempo para o SEI montar a árvore visual
        
        frames_para_testar = [page_processo] + page_processo.frames
        
        documentos = []
        for ctx in frames_para_testar:
            try:
                elementos = ctx.query_selector_all("a.infraArvoreNo, .infraArvoreNo, #divArvore a, a[id*='anchorDoc']")
                for el in elementos:
                    texto = el.inner_text().strip()
                    if not texto:
                        continue
                    if "consultar andamento" in texto.lower():
                        continue
                    # Ignora a raiz do processo
                    if re.match(r"^\d{5}\.\d{6}/\d{4}-\d{2}$", texto):
                        continue
                    if texto not in documentos:
                        documentos.append(texto)
            except Exception:
                continue
        
        qtd_docs = len(documentos)
        esta_vazio = (qtd_docs == 0)
        return esta_vazio, qtd_docs, documentos

    except Exception as e:
        return False, -1, [f"Erro na leitura: {e}"]


def salvar_resultados(resultados):
    """
    Salva os resultados em três formatos:
    1. Planilha Excel detalhada (.xlsx)
    2. Arquivo TXT apenas com NUPs dos vazios (.txt)
    3. Histórico consolidado cumulativo (.csv)
    """
    if not resultados:
        print("[INFO] Nenhum resultado para salvar.")
        return

    garantir_diretorios()
    agora = datetime.now()
    timestamp_arquivo = agora.strftime("%Y-%m-%d_%Hh%M")
    timestamp_humano = agora.strftime("%d/%m/%Y %H:%M:%S")

    df = pd.DataFrame(resultados)
    df["Data_Hora_Auditoria"] = timestamp_humano

    # 1. Planilha Excel organizada em abas
    caminho_excel = os.path.join(PASTA_SAIDAS, f"relatorio_certifica_{timestamp_arquivo}.xlsx")
    with pd.ExcelWriter(caminho_excel, engine="openpyxl") as writer:
        # Aba 1: Processos Vazios (Candidatos à exclusão futura)
        df_vazios = df[df["Vazio"] == True]
        df_vazios.to_excel(writer, sheet_name="Candidatos_Exclusao", index=False)

        # Aba 2: Processos Com Conteúdo (Para analistas)
        df_conteudo = df[df["Vazio"] == False]
        df_conteudo.to_excel(writer, sheet_name="Com_Conteudo", index=False)

        # Aba 3: Todos os analisados
        df.to_excel(writer, sheet_name="Geral_Auditados", index=False)

    print(f"\n[SALVO] Planilha Excel completa: {caminho_excel}")
    print(f"        -> Vazios identificados: {len(df_vazios)}")
    print(f"        -> Com conteúdo: {len(df_conteudo)}")

    # 2. Arquivo TXT com a lista pura de NUPs vazios (um por linha)
    caminho_txt = os.path.join(PASTA_SAIDAS, f"nups_vazios_{timestamp_arquivo}.txt")
    with open(caminho_txt, "w", encoding="utf-8") as f:
        for nup in df_vazios["Processo"]:
            f.write(f"{nup}\n")
    print(f"[SALVO] Lista de NUPs vazios (TXT): {caminho_txt}")

    # 3. Atualiza o histórico consolidado (acumulado dia a dia)
    if os.path.exists(ARQUIVO_HISTORICO):
        df_historico_antigo = pd.read_csv(ARQUIVO_HISTORICO, sep=";")
        df_combinado = pd.concat([df_historico_antigo, df], ignore_index=True)
        # Remove duplicatas se o mesmo processo foi lido no mesmo dia
        df_combinado.drop_duplicates(subset=["Processo", "Data_Hora_Auditoria"], inplace=True)
    else:
        df_combinado = df

    df_combinado.to_csv(ARQUIVO_HISTORICO, sep=";", index=False, encoding="utf-8-sig")
    print(f"[SALVO] Histórico cumulativo atualizado: {ARQUIVO_HISTORICO}")


def executar():
    garantir_diretorios()
    print("=" * 75)
    print("  ROBÔ SEI ANATEL - AUDITORIA DE PROCESSOS CERTIFICA (ORCN)")
    print("  Modo: SALVAMENTO E HISTÓRICO (Nenhuma exclusão será feita)")
    print("=" * 75)

    with sync_playwright() as p:
        print("\n[1/4] Abrindo o Google Chrome...")
        browser = p.chromium.launch(channel="chrome", headless=False)
        context = browser.new_context()
        page = context.new_page()

        print(f"[2/4] Acessando {URL_SEI}...")
        try:
            page.goto(URL_SEI, timeout=60000)
        except Exception:
            pass

        print("\n" + "#" * 60)
        print(">>> AÇÃO NECESSÁRIA NO NAVEGADOR:")
        print("1. Faça seu login com suas credenciais habituais.")
        print("2. Certifique-se de estar na unidade correta (ex: ORCN).")
        print("3. Aguarde a página de 'Controle de Processos' carregar totalmente.")
        print("#" * 60)
        input("\n>>> Quando a tela estiver 100% carregada, aperte ENTER aqui...")

        page = obter_pagina_ativa(context)
        print(f"\n[3/4] Conectado na página: {page.title()}")
        print("-> Aguardando estabilização...")
        aguardar_estabilizacao(page)

        # Mapeia processos na tabela de Gerados
        links_processos = []
        for tentativa in range(3):
            try:
                contextos = [page] + page.frames
                for ctx in contextos:
                    tbl_gerados = ctx.query_selector("#tblProcessosGerados, table[summary*='Processos gerados']")
                    candidatos = tbl_gerados.query_selector_all("a") if tbl_gerados else ctx.query_selector_all("a")

                    for a in candidatos:
                        try:
                            txt = a.inner_text().strip()
                            if re.match(r"^\d{5}\.\d{6}/\d{4}-\d{2}$", txt):
                                tooltip = extrair_info_tooltip(a)
                                href = a.get_attribute("href") or ""
                                url_completa = urljoin(page.url, href) if href else ""
                                
                                if not any(p["nup"] == txt for p in links_processos):
                                    links_processos.append({
                                        "nup": txt,
                                        "tooltip": tooltip,
                                        "url": url_completa,
                                        "eh_certifica": verificar_se_eh_certifica(tooltip)
                                    })
                        except Exception:
                            continue
                
                if links_processos:
                    break
            except Exception:
                time.sleep(2)

        total_processos = len(links_processos)
        processos_certifica = [c for c in links_processos if c["eh_certifica"]]

        print(f"\n-> Processos visíveis na tela: {total_processos}")
        print(f"-> Identificados como Sistema CERTIFICA: {len(processos_certifica)}")

        if not processos_certifica:
            print("[ALERTA] Nenhum processo do CERTIFICA encontrado na tela atual.")
            input("\nPressione ENTER para fechar...")
            browser.close()
            return

        # Pergunta ao usuário quantos processos quer analisar agora
        print("\n" + "-" * 60)
        opcao_qtd = input(
            f"Quantos processos deseja analisar agora? \n"
            f"[Ex: Digite 20, 50, ou aperte ENTER para analisar 20, ou 'T' para todos os {len(processos_certifica)}]: "
        ).strip().upper()

        if opcao_qtd == "T":
            limite = len(processos_certifica)
        elif opcao_qtd.isdigit():
            limite = int(opcao_qtd)
        else:
            limite = 20  # Padrão seguro

        alvos = processos_certifica[:limite]
        print(f"\n[4/4] Iniciando análise de {len(alvos)} processos do CERTIFICA...")
        print("-> Dica: Você pode interromper a qualquer momento com Ctrl+C e o que já foi lido será salvo!\n")

        resultados = []

        try:
            for idx, item in enumerate(alvos, 1):
                nup = item["nup"]
                url_proc = item["url"]
                print(f"[{idx}/{len(alvos)}] Inspecionando: {nup}...")

                proc_page = context.new_page()
                try:
                    proc_page.goto(url_proc, wait_until="domcontentloaded", timeout=30000)
                    aguardar_estabilizacao(proc_page)

                    esta_vazio, qtd_docs, lista_docs = analisar_arvore_processo(proc_page)

                    if esta_vazio:
                        status = "VAZIO"
                        print(f"   -> [VAZIO] Pronto para ser excluído futuramente.")
                    else:
                        status = "COM CONTEÚDO"
                        print(f"   -> [COM CONTEÚDO] Possui {qtd_docs} doc(s): {', '.join(lista_docs[:2])}...")

                    resultados.append({
                        "Processo": nup,
                        "Status": status,
                        "Vazio": esta_vazio,
                        "Qtd_Documentos": qtd_docs,
                        "Documentos": "; ".join(lista_docs),
                        "Origem_Certifica": item["tooltip"]
                    })

                except Exception as err:
                    print(f"   -> [ERRO] {err}")
                    resultados.append({
                        "Processo": nup,
                        "Status": "Erro Leitura",
                        "Vazio": False,
                        "Qtd_Documentos": -1,
                        "Documentos": "",
                        "Origem_Certifica": item["tooltip"]
                    })
                finally:
                    proc_page.close()

        except KeyboardInterrupt:
            print("\n[INTERRUPÇÃO] Processamento pausado pelo usuário. Salvando o que já foi coletado...")

        # Salva em todos os formatos na pasta 'saidas'
        salvar_resultados(resultados)

        print("\n" + "=" * 75)
        print("  OPERAÇÃO FINALIZADA COM SUCESSO!")
        print(f"  Verifique a pasta '{PASTA_SAIDAS}' para consultar os relatórios.")
        print("=" * 75)

        input("\nPressione ENTER para fechar o navegador...")
        browser.close()


if __name__ == "__main__":
    executar()
