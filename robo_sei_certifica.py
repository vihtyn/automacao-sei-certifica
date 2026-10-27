"""
Robô de Automação SEI 5.0.5 - Módulo de Exclusão e Auditoria de Processos CERTIFICA
Desenvolvido para ANATEL / Setor ORCN

Modos de Operação:
1. AUDITORIA: Apenas mapeia e salva relatórios (não exclui nada).
2. SUPERVISIONADO: Pede confirmação no terminal antes de excluir cada processo vazio.
3. AUTOMÁTICO EM LOTE: Exclui diretamente todos os processos vazios identificados.
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
        time.sleep(2.0)  # Tempo para o SEI desenhar os nós da árvore
        
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
                    # Se for apenas o número do processo (nó raiz), não conta como documento
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


def executar_exclusao(proc_page, nup):
    """
    Localiza o botão de lixeira ('Excluir'), clica e confirma o alerta do SEI.
    Retorna: (sucesso: bool, mensagem: str)
    """
    dialogo_capturado = {"mensagem": "", "confirmado": False}

    def tratar_dialogo(dialog):
        dialogo_capturado["mensagem"] = dialog.message
        dialogo_capturado["confirmado"] = True
        print(f"      [POP-UP SEI] '{dialog.message}' -> Aceitando confirmação de exclusão...")
        dialog.accept()

    # Registra o listener de diálogo nativo (confirm / alert do navegador)
    proc_page.on("dialog", tratar_dialogo)

    # Lista de seletores comuns para a lixeira vermelha no SEI 5.0
    seletores_lixeira = [
        "a[title*='Excluir']",
        "a[data-bs-original-title*='Excluir']",
        "a[aria-label*='Excluir']",
        "button[title*='Excluir']",
        "img[alt*='Excluir']",
        "img[title*='Excluir']",
        "a[href*='procedimento_excluir']",
        "a[onclick*='excluir']",
        "#btnExcluirProcesso",
        "a#btnExcluir"
    ]

    contextos = [proc_page] + proc_page.frames
    botao_excluir = None

    for ctx in contextos:
        for sel in seletores_lixeira:
            try:
                el = ctx.query_selector(sel)
                if el and el.is_visible():
                    botao_excluir = el
                    break
            except Exception:
                continue
        if botao_excluir:
            break

    if not botao_excluir:
        return False, "Botão de lixeira ('Excluir') não foi encontrado na barra superior."

    try:
        # Clica na lixeira
        botao_excluir.click()
        
        # Aguarda 1 segundo para dar tempo do tratador de diálogo (tratar_dialogo) agir
        time.sleep(1.0)

        # Se o pop-up da imagem apareceu e foi confirmado, espera a página recarregar e sai
        if dialogo_capturado["confirmado"]:
            try:
                proc_page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass # Ignora timeout se o SEI fechar a aba ou voltar rápido demais
            return True, "Processo excluído com sucesso (Pop-up nativo confirmado)"

        # Caso o SEI não solte o pop-up nativo e use um modal em HTML na tela
        for ctx in contextos:
            try:
                modal_confirm = ctx.query_selector(
                    "button:has-text('Confirmar'), button:has-text('Sim'), button:has-text('OK'), #btnConfirmar"
                )
                if modal_confirm and modal_confirm.is_visible():
                    modal_confirm.click()
                    proc_page.wait_for_load_state("domcontentloaded", timeout=10000)
                    break
            except Exception:
                continue

        return True, "Processo excluído com sucesso no SEI"

    except Exception as e:
        return False, f"Falha ao executar exclusão: {e}"


def salvar_resultados(resultados, modo_operacao):
    """
    Salva os resultados em três formatos na pasta 'saidas/'.
    """
    if not resultados:
        print("[INFO] Nenhum resultado para salvar.")
        return

    garantir_diretorios()
    agora = datetime.now()
    timestamp_arquivo = agora.strftime("%Y-%m-%d_%Hh%M")
    timestamp_humano = agora.strftime("%d/%m/%Y %H:%M:%S")

    df = pd.DataFrame(resultados)
    df["Data_Hora"] = timestamp_humano
    df["Modo_Operacao"] = modo_operacao

    # 1. Planilha Excel detalhada
    caminho_excel = os.path.join(PASTA_SAIDAS, f"relatorio_certifica_{timestamp_arquivo}.xlsx")
    with pd.ExcelWriter(caminho_excel, engine="openpyxl") as writer:
        # Se houve exclusões
        df_excluidos = df[df["Acao_Executada"] == "EXCLUIDO"]
        if not df_excluidos.empty:
            df_excluidos.to_excel(writer, sheet_name="Excluidos", index=False)

        # Processos vazios que não foram excluídos (ex: modo auditoria ou pulados)
        df_vazios_restantes = df[(df["Vazio"] == True) & (df["Acao_Executada"] != "EXCLUIDO")]
        if not df_vazios_restantes.empty:
            df_vazios_restantes.to_excel(writer, sheet_name="Vazios_Pendentes", index=False)

        # Processos com conteúdo
        df_conteudo = df[df["Vazio"] == False]
        if not df_conteudo.empty:
            df_conteudo.to_excel(writer, sheet_name="Com_Conteudo", index=False)

        # Visão Geral
        df.to_excel(writer, sheet_name="Geral_Auditados", index=False)

    print(f"\n[SALVO] Planilha Excel: {caminho_excel}")
    if not df_excluidos.empty:
        print(f"        -> Processos excluídos: {len(df_excluidos)}")

    # 2. Arquivo TXT dos excluídos (se houver) ou dos vazios
    if not df_excluidos.empty:
        caminho_txt = os.path.join(PASTA_SAIDAS, f"nups_excluidos_{timestamp_arquivo}.txt")
        with open(caminho_txt, "w", encoding="utf-8") as f:
            for nup in df_excluidos["Processo"]:
                f.write(f"{nup}\n")
        print(f"[SALVO] Lista de NUPs excluídos (TXT): {caminho_txt}")
    else:
        df_vazios = df[df["Vazio"] == True]
        if not df_vazios.empty:
            caminho_txt = os.path.join(PASTA_SAIDAS, f"nups_vazios_{timestamp_arquivo}.txt")
            with open(caminho_txt, "w", encoding="utf-8") as f:
                for nup in df_vazios["Processo"]:
                    f.write(f"{nup}\n")
            print(f"[SALVO] Lista de NUPs vazios (TXT): {caminho_txt}")

    # 3. Histórico Consolidado (adiciona sem apagar o passado)
    if os.path.exists(ARQUIVO_HISTORICO):
        df_antigo = pd.read_csv(ARQUIVO_HISTORICO, sep=";")
        df_combinado = pd.concat([df_antigo, df], ignore_index=True)
        df_combinado.drop_duplicates(subset=["Processo", "Data_Hora"], inplace=True)
    else:
        df_combinado = df

    df_combinado.to_csv(ARQUIVO_HISTORICO, sep=";", index=False, encoding="utf-8-sig")
    print(f"[SALVO] Histórico cumulativo atualizado: {ARQUIVO_HISTORICO}")


def menu_escolha_modo():
    """Exibe o menu de modos de operação para o usuário."""
    print("\n" + "=" * 65)
    print("  ESCOLHA O MODO DE OPERAÇÃO DO ROBÔ:")
    print("=" * 65)
    print("  [1] MODO AUDITORIA (Seguro: Apenas analisa e salva relatórios)")
    print("  [2] MODO SUPERVISIONADO (Pergunta antes de excluir cada vazio)")
    print("  [3] MODO AUTOMÁTICO EM LOTE (Exclui direto os vazios encontrados)")
    print("=" * 65)
    
    escolha = input("Digite o número da opção desejada [1, 2 ou 3] (Padrão: 2): ").strip()
    
    if escolha == "1":
        return "AUDITORIA"
    elif escolha == "3":
        return "AUTOMATICO"
    else:
        return "SUPERVISIONADO"


def executar():
    garantir_diretorios()
    print("=" * 75)
    print("  ROBÔ SEI ANATEL - PROCESSOS CERTIFICA (ORCN)")
    print("=" * 75)

    modo_operacao = menu_escolha_modo()
    print(f"\n-> Modo selecionado: [{modo_operacao}]")

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

        # Pergunta quantidade a analisar
        print("\n" + "-" * 60)
        sugestao = 5 if modo_operacao == "SUPERVISIONADO" else 20
        opcao_qtd = input(
            f"Quantos processos deseja analisar agora? \n"
            f"[Ex: Digite 5, 20, 50, aperte ENTER para {sugestao}, ou 'T' para todos os {len(processos_certifica)}]: "
        ).strip().upper()

        if opcao_qtd == "T":
            limite = len(processos_certifica)
        elif opcao_qtd.isdigit():
            limite = int(opcao_qtd)
        else:
            limite = sugestao

        alvos = processos_certifica[:limite]
        print(f"\n[4/4] Iniciando processamento de {len(alvos)} processos (Modo: {modo_operacao})...")
        print("-> Dica: Interrompa com Ctrl+C a qualquer momento e os dados coletados serão salvos.\n")

        resultados = []

        try:
            for idx, item in enumerate(alvos, 1):
                nup = item["nup"]
                url_proc = item["url"]
                print(f"\n[{idx}/{len(alvos)}] Inspecionando: {nup}...")

                proc_page = context.new_page()
                try:
                    proc_page.goto(url_proc, wait_until="domcontentloaded", timeout=30000)
                    aguardar_estabilizacao(proc_page)

                    esta_vazio, qtd_docs, lista_docs = analisar_arvore_processo(proc_page)
                    acao_executada = "NENHUMA"
                    msg_exclusao = ""

                    if not esta_vazio:
                        status = "COM CONTEÚDO"
                        acao_executada = "IGNORADO_COM_CONTEUDO"
                        print(f"   -> [COM CONTEÚDO] Possui {qtd_docs} doc(s): {', '.join(lista_docs[:2])}...")
                        print(f"      [SEGURANÇA] Processo protegido. Não será excluído!")
                    else:
                        status = "VAZIO"
                        print(f"   -> [VAZIO] Nenhum documento na árvore!")

                        # Decisão com base no modo
                        if modo_operacao == "AUDITORIA":
                            acao_executada = "AUDITADO_VAZIO"
                            print("      [AUDITORIA] Processo catalogado (exclusão desligada).")

                        elif modo_operacao == "SUPERVISIONADO":
                            confirma = input(f"\n   >>> ATENÇÃO: Deseja EXCLUIR o processo vazio {nup}? (s/n): ").strip().lower()
                            if confirma == "s":
                                print("      -> Executando exclusão...")
                                ok, msg_exclusao = executar_exclusao(proc_page, nup)
                                if ok:
                                    acao_executada = "EXCLUIDO"
                                    print(f"      -> SUCESSO: {nup} foi excluído!")
                                else:
                                    acao_executada = "FALHA_EXCLUSAO"
                                    print(f"      -> AVISO: {msg_exclusao}")
                            else:
                                acao_executada = "PULADO_PELO_USUARIO"
                                print("      -> Exclusão cancelada pelo usuário.")

                        elif modo_operacao == "AUTOMATICO":
                            print("      -> [AUTOMÁTICO] Excluindo processo...")
                            ok, msg_exclusao = executar_exclusao(proc_page, nup)
                            if ok:
                                acao_executada = "EXCLUIDO"
                                print(f"      -> SUCESSO: {nup} foi excluído!")
                            else:
                                acao_executada = "FALHA_EXCLUSAO"
                                print(f"      -> AVISO: {msg_exclusao}")

                    resultados.append({
                        "Processo": nup,
                        "Status": status,
                        "Vazio": esta_vazio,
                        "Qtd_Documentos": qtd_docs,
                        "Acao_Executada": acao_executada,
                        "Detalhe_Acao": msg_exclusao,
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
                        "Acao_Executada": "ERRO",
                        "Detalhe_Acao": str(err),
                        "Documentos": "",
                        "Origem_Certifica": item["tooltip"]
                    })
                finally:
                    proc_page.close()

        except KeyboardInterrupt:
            print("\n[INTERRUPÇÃO] Processamento pausado pelo usuário. Salvando o que já foi processado...")

        # Salva os resultados
        salvar_resultados(resultados, modo_operacao)

        print("\n" + "=" * 75)
        print("  OPERAÇÃO FINALIZADA!")
        print(f"  Verifique a pasta '{PASTA_SAIDAS}' para consultar os relatórios gerados.")
        print("=" * 75)

        input("\nPressione ENTER para fechar o navegador...")
        browser.close()


if __name__ == "__main__":
    executar()
