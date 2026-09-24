'''
Aplicaçâo Web Integrada de Relatório Semanal de Obras (SINFRA / TJRR) - Versão v30
Modelo de Relatório v68 Restaurado com Design Arredondado Executivo:
- Design do Relatório PDF v68:
  1. Cabeçalho Institucional Pantone 289 C com bordas e linhas limpas.
  2. Caixa de Indicadores e Prazos com cantos arredondados (round_corners=True, corner_radius=3.5).
  3. Barra de progresso do tempo decorrido com cantos arredondados.
  4. Tabela 1: Identificação do Contrato e da Obra com cabeçalho azul-marinho.
  5. Tabela 2: Atividades Realizadas na Semana Atual.
  6. Seção 3: Atividades da Semana Passada (Histórico Anterior) em container arredondado tom âmbar suave.
  7. Bloco de Assinatura do Fiscal Responsável.
- Recursos da Aplicação Preservados:
  - Tela de Login v14 com marca d'água SIN FRA.
  - Sidebar Fixa no Dashboard.
  - RBAC por perfil (Admin: 5 módulos, Fiscal: 4 módulos, Visualizador: 1 módulo).
  - Designação exclusiva de fiscal pelo Admin e cadastro de novas contas como Visualizador por padrão.
  - Esqueci a senha funcional com OTP de 6 dígitos.
  - Campos de texto independentes para Atividades e Histórico Anterior.

Execução Standalone Nativa (sem dependências externas):
python app_relatorio_obras_sinfra_tjrr_v30.py
'''

import os
import http.server
import socketserver
import webbrowser
import threading
import socket
import sqlite3
import hashlib
import secrets
import time
import json
import urllib.parse
import datetime
import html as html_lib
from contextlib import closing
from fpdf import FPDF
from fpdf.fonts import FontFace
from fpdf.enums import XPos, YPos

DB_NAME = "sinfra_v30.db"
DEFAULT_PORTS = [8000, 8080, 8001, 8888]

# Cores para o PDF (Pantone 289 C / Emerald Green / Slate)
COR_NAVY = (12, 35, 64)          # #0C2340
COR_BLUE_LIGHT = (240, 249, 255)  # #F0F9FF
COR_BLUE_BORDER = (186, 230, 253) # #BAE6FD
COR_GREEN = (0, 135, 90)         # #00875A
COR_GREEN_LIGHT = (236, 253, 245) # #ECFDF5
COR_SLATE_DARK = (15, 23, 42)    # #0F172A
COR_SLATE_TEXT = (51, 65, 85)    # #334155
COR_MUTED = (100, 116, 139)      # #64748B
COR_BORDER = (203, 213, 225)     # #CBD5E1
COR_LIGHT_BG = (248, 250, 252)   # #F8FAFC

def sanitize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).replace("✓", "[X]").replace("✔", "[X]").replace("—", "-").replace("•", "-")
    return text.encode("latin-1", "replace").decode("latin-1")

def esc(text: str) -> str:
    return html_lib.escape(str(text or ""))

# =========================================================================
# BANCO DE DADOS SQLITE (MODO WAL)
# =========================================================================
def get_db():
    conn = sqlite3.connect(DB_NAME, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    with closing(get_db()) as conn:
        with conn:
            # Tabela de Usuários
            conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT UNIQUE NOT NULL,
                nome TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                senha_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                perfil TEXT NOT NULL DEFAULT 'visualizador',
                cargo TEXT NOT NULL DEFAULT 'Visualizador SINFRA',
                ativo INTEGER DEFAULT 1,
                criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Tabela de Obras
            conn.execute("""
            CREATE TABLE IF NOT EXISTS obras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                endereco TEXT NOT NULL,
                contrato TEXT NOT NULL,
                ordem_servico TEXT NOT NULL,
                processo_sei TEXT NOT NULL,
                empreiteira TEXT NOT NULL,
                fiscal_id INTEGER,
                fiscal_nome TEXT,
                prazo_inicio DATE NOT NULL,
                prazo_fim DATE NOT NULL,
                atividades_json TEXT DEFAULT '[]',
                historico_anterior TEXT DEFAULT '',
                ativa INTEGER DEFAULT 1
            )
            """)

            # Tabela de Histórico Semanal de Relatórios
            conn.execute("""
            CREATE TABLE IF NOT EXISTS relatorios_semanais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                obra_id INTEGER NOT NULL,
                codigo_relatorio TEXT NOT NULL,
                periodo_ref TEXT NOT NULL,
                atividades_json TEXT NOT NULL,
                historico_anterior TEXT,
                fiscal_nome TEXT NOT NULL,
                data_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (obra_id) REFERENCES obras(id)
            )
            """)

            # Tabela de Logs de Auditoria
            conn.execute("""
            CREATE TABLE IF NOT EXISTS logs_auditoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_hora TEXT NOT NULL,
                usuario TEXT NOT NULL,
                acao TEXT NOT NULL,
                detalhes TEXT
            )
            """)

            # Tabela de Recuperação de Senha (OTP)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS recuperacao_senha (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                codigo TEXT NOT NULL,
                usado INTEGER DEFAULT 0,
                criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Seed Admin se não existir
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM usuarios WHERE login = 'admin'")
            if not cursor.fetchone():
                salt_a = secrets.token_hex(16)
                hash_a = hashlib.pbkdf2_hmac('sha256', 'TJRR@2026admin'.encode(), salt_a.encode(), 100000).hex()
                cursor.execute("""
                INSERT INTO usuarios (login, nome, email, senha_hash, salt, perfil, cargo)
                VALUES ('admin', 'Administrador SINFRA', 'admin.sinfra@tjrr.jus.br', ?, ?, 'admin', 'Subsecretário de Infraestrutura')
                """, (hash_a, salt_a))

                atividades_init = [
                    "Confecção de vestiário, almoxarifado e refeitório;",
                    "Confecção de sistema de fossa provisória;",
                    "Remoção de placas de estacionamento;",
                    "Desmontagem das estruturas de policarbonato (rampas e escadas);",
                    "Remoção de piso intertravado."
                ]
                historico_init = """- Instalação de tapume de vedação do canteiro de obras
- Mobilização do container escritório e banheiros
- Confecção do vestiário"""

                cursor.execute("""
                INSERT INTO obras (nome, endereco, contrato, ordem_servico, processo_sei, empreiteira, fiscal_id, fiscal_nome, prazo_inicio, prazo_fim, atividades_json, historico_anterior)
                VALUES (?, ?, ?, ?, ?, ?, 1, 'Administrador SINFRA', '2026-07-01', '2027-08-16', ?, ?)
                """, (
                    "Construção do Anexo do Palácio da Justiça de Roraima",
                    "Praça do Centro Cívico, nº 296 - Centro, Boa Vista - RR",
                    "Contrato nº 14/2026 - TJRR",
                    "OS nº 001/2026-SINFRA",
                    "0012760-16.2026.8.23.8000",
                    "Construtora Norte Engenharia EIRELI",
                    json.dumps(atividades_init),
                    historico_init
                ))

init_db()

# =========================================================================
# GERADOR DE RELATÓRIO PDF (MODELO V68 RESTAURADO COM DESIGN ARREDONDADO)
# =========================================================================
class RelatorioArredondadov68(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pdf_font = "Helvetica"
        ttf_paths = [
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
            ("C:\\Windows\\Fonts\\calibri.ttf",
             "C:\\Windows\\Fonts\\calibrib.ttf",
             "C:\\Windows\\Fonts\\calibrii.ttf"),
            ("C:\\Windows\\Fonts\\arial.ttf",
             "C:\\Windows\\Fonts\\arialbd.ttf",
             "C:\\Windows\\Fonts\\ariali.ttf"),
        ]
        for reg, bold, ital in ttf_paths:
            if os.path.exists(reg) and os.path.exists(bold) and os.path.exists(ital):
                try:
                    self.add_font("Calibri", "", reg)
                    self.add_font("Calibri", "B", bold)
                    self.add_font("Calibri", "I", ital)
                    self.pdf_font = "Calibri"
                    break
                except Exception:
                    pass

    def header(self):
        self.set_fill_color(*COR_NAVY)
        self.rect(0, 0, 210, 2.5, style="F")
        self.set_xy(12, 7)
        self.set_font(self.pdf_font, "B", 8)
        self.set_text_color(*COR_NAVY)
        self.cell(0, 4, "PODER JUDICIÁRIO DE RORAIMA - TJRR | SUBSECRETARIA DE INFRAESTRUTURA (SINFRA)", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
        self.set_draw_color(*COR_BORDER)
        self.set_line_width(0.3)
        self.line(12, self.get_y() + 1, 198, self.get_y() + 1)
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font(self.pdf_font, "I", 8)
        self.set_text_color(*COR_MUTED)
        agora = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M")
        self.cell(100, 5, f"Data de Emissão: {agora} | SINFRA TJRR", align="L")
        self.cell(86, 5, f"Página {self.page_no()}", align="R")

def generate_pdf_bytes(obra_dict, atividades, historico):
    pdf = RelatorioArredondadov68(orientation="P", unit="mm", format="A4")
    pdf.set_margins(12, 14, 12)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # 1. TÍTULO E SUBTÍTULO INSTITUCIONAL
    pdf.set_font(pdf.pdf_font, "B", 13)
    pdf.set_text_color(*COR_NAVY)
    pdf.cell(0, 6, "RELATÓRIO SEMANAL DE FISCALIZAÇÃO DE OBRAS", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")

    pdf.set_font(pdf.pdf_font, "I", 8.5)
    pdf.set_text_color(*COR_MUTED)
    pdf.cell(0, 4.5, f"Tribunal de Justiça do Estado de Roraima - {obra_dict.get('nome', '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
    pdf.ln(2.5)

    # 2. CAIXA DE INDICADORES E PRAZOS (ARREDONDADA V68 - SÓ DATA DE EMISSÃO)
    pdf.set_fill_color(*COR_LIGHT_BG)
    pdf.set_draw_color(*COR_BORDER)
    y_box = pdf.get_y()
    pdf.rect(12, y_box, 186, 21, style="FD", round_corners=True, corner_radius=3.5)

    dt_inicio = str(obra_dict.get('prazo_inicio', '2026-07-01'))
    dt_fim = str(obra_dict.get('prazo_fim', '2027-08-16'))
    try:
        d1 = datetime.datetime.strptime(dt_inicio, '%Y-%m-%d')
        d2 = datetime.datetime.strptime(dt_fim, '%Y-%m-%d')
        hoje = datetime.datetime.now()
        tot_dias = max((d2 - d1).days, 1)
        dec_dias = max(min((hoje - d1).days, tot_dias), 0)
        pct_prazo = min(max(int((dec_dias / tot_dias) * 100), 0), 100)
        d1_str = d1.strftime('%d/%m/%Y')
        d2_str = d2.strftime('%d/%m/%Y')
    except Exception:
        d1_str, d2_str = '01/07/2026', '16/08/2027'
        pct_prazo, dec_dias, tot_dias = 20, 83, 411

    data_emissao_str = datetime.datetime.now().strftime('%d/%m/%Y')

    pdf.set_xy(15, y_box + 2.5)
    pdf.set_font(pdf.pdf_font, "B", 8.5)
    pdf.set_text_color(*COR_NAVY)
    pdf.cell(60, 4, f"Início: {d1_str}", align="L")
    pdf.cell(66, 4, f"Data de Emissão: {data_emissao_str}", align="C")
    pdf.cell(54, 4, f"Término Previsto: {d2_str}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # BARRA DE PROGRESSO ARREDONDADA
    bar_y = y_box + 8.5
    pdf.set_fill_color(226, 232, 240)
    pdf.rect(15, bar_y, 180, 3.5, style="F", round_corners=True, corner_radius=1.8)
    pdf.set_fill_color(*COR_GREEN)
    fill_w = max(180 * (pct_prazo / 100), 2)
    pdf.rect(15, bar_y, fill_w, 3.5, style="F", round_corners=True, corner_radius=1.8)

    pdf.set_xy(15, bar_y + 4.5)
    pdf.set_font(pdf.pdf_font, "", 8.5)
    pdf.set_text_color(*COR_SLATE_TEXT)
    pdf.cell(110, 4, f"Tempo Decorrido do Contrato: {dec_dias} de {tot_dias} dias ({pct_prazo}%)", align="L")
    pdf.set_font(pdf.pdf_font, "B", 8.5)
    pdf.set_text_color(*COR_GREEN)
    pdf.cell(70, 4, "SITUAÇÃO: EM CONFORMIDADE", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(y_box + 24)

    # 3. TABELA 1: DADOS DA OBRA (SEM INTERCALAÇÃO DE CORES / ZEBRA STRIPING)
    pdf.set_font(pdf.pdf_font, "B", 10)
    pdf.set_text_color(*COR_NAVY)
    pdf.cell(0, 5, "1. IDENTIFICAÇÃO DO CONTRATO E DA OBRA", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)

    fields = [
        ("Obra Acompanhada:", obra_dict.get('nome', '')),
        ("Endereço Completo:", obra_dict.get('endereco', '')),
        ("Empresa Executora:", obra_dict.get('empreiteira', '')),
        ("Nº do Contrato:", obra_dict.get('contrato', '')),
        ("Processo SEI:", obra_dict.get('processo_sei', '')),
        ("Ordem de Serviço:", obra_dict.get('ordem_servico', '')),
        ("Fiscal Responsável:", obra_dict.get('fiscal_nome', ''))
    ]

    header_bold_style = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=COR_NAVY)
    label_bold_style = FontFace(emphasis="BOLD", color=COR_NAVY, fill_color=(255, 255, 255))
    data_regular_style = FontFace(color=COR_SLATE_TEXT, fill_color=(255, 255, 255))

    pdf.set_draw_color(*COR_BORDER)
    # ATENÇÃO: SEM cell_fill_mode="ROWS" PARA EVITAR INTERCALAÇÃO DE CORES
    with pdf.table(
        col_widths=(46, 140),
        headings_style=header_bold_style,
        line_height=5.2,
        text_align="LEFT",
        borders_layout="HORIZONTAL_LINES"
    ) as table:
        hdr = table.row()
        hdr.cell("Campo")
        hdr.cell("Informação Oficial")

        for campo, valor in fields:
            row = table.row()
            # Rótulo em Bold, sem intercalação
            row.cell(campo, style=label_bold_style)
            # Dado/Input em Fonte Regular (SEM BOLD), sem intercalação
            row.cell(str(valor), style=data_regular_style)

    pdf.ln(4)

    # 4. TABELA 2: ATIVIDADES DA SEMANA ATUAL (SEM INTERCALAÇÃO DE CORES)
    pdf.set_font(pdf.pdf_font, "B", 10)
    pdf.set_text_color(*COR_NAVY)
    pdf.cell(0, 5, "2. ATIVIDADES REALIZADAS NA SEMANA ATUAL", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)

    atividades_clean = [a.strip() for a in atividades if str(a).strip()]

    with pdf.table(
        col_widths=(186,),
        headings_style=header_bold_style,
        line_height=5.8,
        text_align="LEFT",
        borders_layout="HORIZONTAL_LINES"
    ) as table:
        hdr = table.row()
        hdr.cell("Descrição da Atividade Executada no Período")

        if atividades_clean:
            for act in atividades_clean:
                row = table.row(style=data_regular_style)
                bullet_act = f"-  {act}" if not act.startswith("-") else act
                row.cell(bullet_act)
        else:
            row = table.row(style=data_regular_style)
            row.cell("Nenhuma atividade registrada para esta semana.")

    pdf.ln(4)

    # 5. ATIVIDADES DA SEMANA PASSADA / HISTÓRICO ANTERIOR (CAIXA ARREDONDADA COM DADOS REGULARES)
    if historico.strip():
        pdf.set_font(pdf.pdf_font, "B", 10)
        pdf.set_text_color(*COR_NAVY)
        pdf.cell(0, 5, "3. ATIVIDADES DA SEMANA PASSADA (HISTÓRICO ANTERIOR)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)

        y_hist = pdf.get_y()
        hist_lines = [h.strip() for h in historico.split('\n') if h.strip()]

        box_h = max(len(hist_lines) * 4.5 + 6, 12)
        pdf.set_fill_color(255, 251, 235) # Amarelo muito suave
        pdf.set_draw_color(253, 230, 138)
        pdf.rect(12, y_hist, 186, box_h, style="FD", round_corners=True, corner_radius=3.5)

        pdf.set_xy(15, y_hist + 3)
        pdf.set_font(pdf.pdf_font, "", 8.5) # Fonte Regular
        pdf.set_text_color(120, 53, 15)
        for line in hist_lines:
            bullet_line = f"-  {line}" if not line.startswith("-") else line
            pdf.cell(180, 4.2, bullet_line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_y(y_hist + box_h + 4)

    # 6. BLOCO DE ASSINATURA DO FISCAL
    pdf.ln(4)
    y_sig = pdf.get_y()

    if y_sig > 250:
        pdf.add_page()
        y_sig = pdf.get_y()

    pdf.set_draw_color(*COR_MUTED)
    pdf.set_line_width(0.3)
    pdf.line(55, y_sig + 6, 155, y_sig + 6)

    pdf.set_xy(12, y_sig + 8)
    pdf.set_font(pdf.pdf_font, "B", 9)
    pdf.set_text_color(*COR_NAVY)
    pdf.cell(186, 4, obra_dict.get('fiscal_nome', 'Administrador SINFRA'), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font(pdf.pdf_font, "", 8) # Regular
    pdf.set_text_color(*COR_MUTED)
    pdf.cell(186, 4, "Fiscal de Obra Responsável - SINFRA / TJRR", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())

LOGIN_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TJRR - SINFRA | Login no Sistema de Obras</title>
<style>
  :root {{
    --bg-main: #0B192C;
    --bg-card: #FFFFFF;
    --navy-dark: #0A192F;
    --blue-accent: #0284C7;
    --blue-hover: #0369A1;
    --text-primary: #0F172A;
    --text-secondary: #475569;
    --border: #E2E8F0;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}

  body {{
    background: var(--bg-main);
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 20px;
    position: relative;
    overflow-x: hidden;
  }}

  .overlay {{
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    background: radial-gradient(circle at 50% 30%, rgba(2, 132, 199, 0.15), transparent 70%);
    pointer-events: none;
  }}

  .sinfra-watermark {{
    position: absolute;
    right: 5%;
    bottom: 5%;
    font-size: 14vw;
    font-weight: 900;
    color: rgba(255, 255, 255, 0.03);
    user-select: none;
    line-height: 0.8;
    text-align: right;
  }}

  .login-card {{
    background: var(--bg-card);
    width: 100%;
    max-width: 440px;
    border-radius: 16px;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
    overflow: hidden;
    z-index: 10;
  }}

  .card-header {{
    background: var(--navy-dark);
    color: white;
    padding: 28px 24px 20px;
    text-align: center;
    border-bottom: 3px solid var(--blue-accent);
  }}

  .institution-tag {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    color: var(--blue-accent);
    display: block;
    margin-bottom: 6px;
  }}

  .app-title {{
    font-size: 18px;
    font-weight: 800;
    color: #FFFFFF;
  }}

  .tabs-nav {{
    display: flex;
    background: #F1F5F9;
    border-bottom: 1px solid var(--border);
  }}

  .tab-btn {{
    flex: 1;
    padding: 14px 10px;
    font-size: 12px;
    font-weight: 700;
    color: var(--text-secondary);
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
    border-bottom: 2px solid transparent;
  }}

  .tab-btn.active {{
    background: white;
    color: var(--blue-accent);
    border-bottom-color: var(--blue-accent);
  }}

  .tab-content {{
    display: none;
    padding: 24px;
  }}

  .tab-content.active {{
    display: block;
  }}

  .form-group {{
    margin-bottom: 16px;
  }}

  .form-label {{
    display: block;
    font-size: 12px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 6px;
  }}

  .form-input {{
    width: 100%;
    padding: 10px 14px;
    border-radius: 8px;
    border: 1px solid var(--border);
    font-size: 13.5px;
    outline: none;
    transition: border-color 0.2s;
  }}

  .form-input:focus {{
    border-color: var(--blue-accent);
    box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.15);
  }}

  .btn-primary {{
    width: 100%;
    padding: 12px;
    background: var(--blue-accent);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 13.5px;
    font-weight: 700;
    cursor: pointer;
    transition: background 0.2s;
  }}

  .btn-primary:hover {{
    background: var(--blue-hover);
  }}

  .card-footer {{
    background: #F8FAFC;
    padding: 14px;
    text-align: center;
    font-size: 11px;
    color: var(--text-secondary);
    border-top: 1px solid var(--border);
  }}

  .msg-banner {{
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 700;
    margin: 16px 24px 0;
    text-align: center;
  }}
  .msg-banner.success {{ background: #ECFDF5; color: #065F46; border: 1px solid #A7F3D0; }}
  .msg-banner.error {{ background: #FEF2F2; color: #991B1B; border: 1px solid #FECACA; }}
</style>
</head>
<body>

<div class="overlay"></div>

<div class="sinfra-watermark">
  <span>SIN</span>
  <span>FRA</span>
</div>

<div class="login-card">
  <div class="card-header">
    <span class="institution-tag">TJRR - SUBSECRETARIA DE INFRAESTRUTURA</span>
    <h2 class="app-title">RELATÓRIO SEMANAL DE OBRAS</h2>
  </div>

  {MSG_BANNER_HTML}

  <div class="tabs-nav">
    <div class="tab-btn {TAB_LOGIN_ACTIVE}" onclick="switchTab('login')">LOGIN</div>
    <div class="tab-btn {TAB_CRIAR_ACTIVE}" onclick="switchTab('criar-conta')">CRIAR CONTA</div>
  </div>

  <!-- Aba 1: LOGIN -->
  <div id="tab-login" class="tab-content {TAB_LOGIN_ACTIVE}">
    <form action="/login" method="POST">
      <div class="form-group">
        <label class="form-label">Usuário ou E-mail</label>
        <input type="text" name="usuario" class="form-input" placeholder="Digite seu usuário ou e-mail" required>
      </div>
      <div class="form-group">
        <label class="form-label">Senha</label>
        <input type="password" name="senha" class="form-input" placeholder="Digite sua senha" required>
      </div>
      <button type="submit" class="btn-primary">ENTRAR NO SISTEMA</button>
    </form>
  </div>

  <!-- Aba 2: CRIAR CONTA -->
  <div id="tab-criar-conta" class="tab-content {TAB_CRIAR_ACTIVE}">
    <form action="/criar_conta" method="POST">
      <div class="form-group">
        <label class="form-label">Nome Completo</label>
        <input type="text" name="nome" class="form-input" placeholder="Digite seu nome completo" required>
      </div>
      <div class="form-group">
        <label class="form-label">E-mail Institucional</label>
        <input type="email" name="email" class="form-input" placeholder="seu.nome@tjrr.jus.br" required>
      </div>
      <div class="form-group">
        <label class="form-label">Nome de Usuário (Login)</label>
        <input type="text" name="usuario" class="form-input" placeholder="Crie um nome de usuário" required>
      </div>
      <div class="form-group">
        <label class="form-label">Senha</label>
        <input type="password" name="senha" class="form-input" placeholder="Crie uma senha forte" required>
      </div>
      <p style="font-size:11px; color:#64748B; margin-bottom:12px;">ℹ️ Toda nova conta é criada como <strong>Visualizador</strong>. O Administrador pode alterar seu perfil posteriormente.</p>
      <button type="submit" class="btn-primary">CRIAR MINHA CONTA</button>
    </form>
  </div>

  <div class="card-footer">
    Subsecretaria de Infraestrutura — TJRR © 2026
  </div>
</div>

<script>
  function switchTab(tabName) {{
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

    if (tabName === 'login') {{
      document.querySelectorAll('.tab-btn')[0].classList.add('active');
      document.getElementById('tab-login').classList.add('active');
    }} else if (tabName === 'criar-conta') {{
      document.querySelectorAll('.tab-btn')[1].classList.add('active');
      document.getElementById('tab-criar-conta').classList.add('active');
    }}
  }}
</script>

</body>
</html>
"""

DASHBOARD_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TJRR - Relatório Semanal de Fiscalização de Obras (SINFRA)</title>
<style>
  :root {{
    --bg-main: #0B192C;
    --bg-card: #FFFFFF;
    --navy-dark: #0A192F;
    --navy-medium: #1E293B;
    --blue-accent: #0284C7;
    --blue-hover: #0369A1;
    --blue-light: #F0F9FF;
    --blue-border: #BAE6FD;
    --text-primary: #0F172A;
    --text-secondary: #475569;
    --text-muted: #94A3B8;
    --green-success: #10B981;
    --green-light: #ECFDF5;
    --border-color: #E2E8F0;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }}

  body {{ background-color: #F8FAFC; color: var(--text-primary); min-height: 100vh; display: flex; flex-direction: column; }}

  header {{ background: linear-gradient(135deg, #0A192F 0%, #0F4C81 100%); color: #FFFFFF; padding: 16px 32px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 12px rgba(10, 25, 47, 0.15); position: sticky; top: 0; z-index: 100; }}
  .header-brand {{ display: flex; align-items: center; gap: 16px; }}
  .brand-logo-badge {{ background: rgba(255, 255, 255, 0.12); border: 1px solid rgba(255, 255, 255, 0.25); padding: 6px 12px; border-radius: 8px; font-weight: 900; font-size: 16px; letter-spacing: 1px; }}
  .brand-title-group h1 {{ font-size: 18px; font-weight: 800; letter-spacing: -0.3px; line-height: 1.2; }}
  .brand-title-group p {{ font-size: 12px; color: #93C5FD; font-weight: 500; }}

  .header-user {{ display: flex; align-items: center; gap: 16px; }}
  .user-badge-card {{ background: rgba(255, 255, 255, 0.1); backdrop-filter: blur(8px); border: 1px solid rgba(255, 255, 255, 0.18); padding: 6px 14px; border-radius: 12px; display: flex; align-items: center; gap: 10px; }}
  .user-avatar {{ width: 32px; height: 32px; background: #0284C7; color: #FFFFFF; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 13px; }}
  .user-info-text {{ font-size: 11.5px; }}
  .user-info-text strong {{ display: block; font-size: 12.5px; color: #FFFFFF; }}
  .role-pill {{ display: inline-block; background: #38BDF8; color: #0F172A; font-size: 9.5px; font-weight: 800; padding: 2px 6px; border-radius: 10px; text-transform: uppercase; }}

  .btn-logout {{ background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #FCA5A5; padding: 8px 14px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; text-decoration: none; transition: all 0.2s; }}
  .btn-logout:hover {{ background: rgba(239, 68, 68, 0.3); color: #FFFFFF; }}

  .app-container {{ display: flex; flex: 1; }}

  /* SIDEBAR FIXA PERMANENTE */
  aside {{ width: 280px; background: #FFFFFF; border-right: 1px solid var(--border-color); padding: 20px 16px; display: flex; flex-direction: column; gap: 24px; box-shadow: 2px 0 8px rgba(0, 0, 0, 0.02); position: sticky; top: 72px; height: calc(100vh - 72px); flex-shrink: 0; }}
  .sidebar-section-title {{ font-size: 11px; font-weight: 800; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px; padding-left: 6px; }}
  .select-work-card {{ background: #F8FAFC; border: 1.5px solid var(--border-color); border-radius: 12px; padding: 12px; }}
  .select-work-card label {{ font-size: 11px; font-weight: 700; color: var(--text-secondary); display: block; margin-bottom: 6px; text-transform: uppercase; }}
  .work-dropdown {{ width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #CBD5E1; background: #FFFFFF; font-size: 12.5px; font-weight: 700; color: var(--text-primary); outline: none; }}
  .work-meta-badge {{ margin-top: 8px; font-size: 11px; color: var(--blue-accent); background: var(--blue-light); padding: 6px 10px; border-radius: 6px; font-weight: 700; display: flex; justify-content: space-between; }}

  .nav-menu {{ list-style: none; display: flex; flex-direction: column; gap: 6px; }}
  .nav-item-btn {{ display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-radius: 10px; color: var(--text-secondary); font-size: 12.5px; font-weight: 700; text-decoration: none; cursor: pointer; border: none; background: transparent; width: 100%; text-align: left; transition: all 0.2s; }}
  .nav-item-btn:hover {{ background: #F1F5F9; color: var(--blue-accent); }}
  .nav-item-btn.active {{ background: var(--blue-light); color: var(--blue-accent); border-left: 4px solid var(--blue-accent); font-weight: 800; }}

  main {{ flex: 1; padding: 28px 36px; max-width: 1400px; width: 100%; min-width: 0; }}

  .module-view {{ display: none; animation: fadeIn 0.25s ease-in-out; }}
  .module-view.active {{ display: block; }}
  @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(4px); }} to {{ opacity: 1; transform: translateY(0); }} }}

  .overview-header-card {{ background: #FFFFFF; border-radius: 16px; padding: 20px 24px; border: 1px solid var(--border-color); box-shadow: 0 2px 4px rgba(0,0,0,0.03); margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }}
  .overview-header-title h2 {{ font-size: 20px; font-weight: 800; color: var(--text-primary); }}
  .overview-header-title p {{ font-size: 13px; color: var(--text-secondary); margin-top: 4px; }}
  .update-tag {{ background: var(--green-light); color: #065F46; border: 1px solid #A7F3D0; padding: 6px 14px; border-radius: 20px; font-size: 11.5px; font-weight: 700; }}

  .progress-card {{ background: #FFFFFF; border-radius: 16px; padding: 20px 24px; border: 1px solid var(--border-color); box-shadow: 0 2px 4px rgba(0,0,0,0.03); margin-bottom: 20px; }}
  .progress-card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
  .progress-card-title {{ font-size: 14px; font-weight: 800; color: var(--text-primary); }}
  .progress-card-perc {{ font-size: 13px; font-weight: 800; color: var(--blue-accent); background: var(--blue-light); padding: 4px 12px; border-radius: 20px; }}
  .progress-bar-bg {{ height: 10px; background: #E2E8F0; border-radius: 10px; overflow: hidden; margin-bottom: 14px; }}
  .progress-bar-fill {{ height: 100%; width: 20%; background: linear-gradient(90deg, #0284C7 0%, #38BDF8 100%); border-radius: 10px; }}
  .timeline-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; background: #F8FAFC; padding: 14px; border-radius: 10px; border: 1px solid #EDF2F7; }}
  .timeline-item span {{ display: block; font-size: 11px; color: var(--text-muted); font-weight: 700; margin-bottom: 2px; }}
  .timeline-item strong {{ font-size: 13px; color: var(--text-primary); }}

  .details-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
  .section-card {{ background: #FFFFFF; border-radius: 16px; padding: 22px 26px; border: 1px solid var(--border-color); box-shadow: 0 2px 4px rgba(0,0,0,0.03); margin-bottom: 20px; }}
  .section-card-title {{ font-size: 15px; font-weight: 800; color: var(--text-primary); margin-bottom: 16px; padding-bottom: 10px; border-bottom: 2px solid #F1F5F9; display: flex; align-items: center; gap: 8px; }}

  .info-table {{ width: 100%; border-collapse: collapse; }}
  .info-table td {{ padding: 8px 0; font-size: 12.5px; border-bottom: 1px dashed #E2E8F0; }}
  .info-label {{ color: var(--text-secondary); font-weight: 700; width: 38%; }}
  .info-val {{ color: var(--text-primary); font-weight: 600; }}

  .checklist-list {{ list-style: none; display: flex; flex-direction: column; gap: 10px; }}
  .check-item {{ display: flex; align-items: flex-start; gap: 10px; background: #F8FAFC; padding: 10px 14px; border-radius: 8px; border: 1px solid #E2E8F0; font-size: 12.5px; font-weight: 600; }}
  .check-badge {{ width: 20px; height: 20px; background: #10B981; color: #FFFFFF; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 900; flex-shrink: 0; }}

  .history-box {{ margin-top: 16px; background: #FFFBEB; border: 1px solid #FDE68A; border-radius: 10px; padding: 12px 16px; }}
  .history-box h4 {{ font-size: 11.5px; font-weight: 800; color: #B45309; text-transform: uppercase; margin-bottom: 4px; }}
  .history-box p {{ font-size: 12px; color: #78350F; line-height: 1.4; white-space: pre-line; }}

  .export-bar-card {{ background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%); border-radius: 16px; padding: 20px 28px; color: #FFFFFF; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
  .btn-pdf-primary {{ background: #EF4444; color: #FFFFFF; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 800; font-size: 12.5px; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 8px; transition: all 0.2s; }}
  .btn-pdf-primary:hover {{ background: #DC2626; transform: translateY(-1px); }}

  .form-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }}
  .form-group-full {{ grid-column: span 2; }}
  .form-group label {{ display: block; font-size: 12px; font-weight: 700; color: var(--text-secondary); margin-bottom: 6px; }}
  .form-group input, .form-group textarea, .form-group select {{ width: 100%; padding: 10px 14px; border-radius: 8px; border: 1.5px solid #CBD5E1; background: #F8FAFC; font-size: 13px; color: var(--text-primary); outline: none; }}
  .form-group input:focus, .form-group textarea:focus {{ border-color: var(--blue-accent); background: #FFFFFF; box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.15); }}
  .btn-save-submit {{ background: linear-gradient(135deg, #0284C7 0%, #0369A1 100%); color: #FFFFFF; border: none; padding: 12px 24px; border-radius: 8px; font-weight: 800; font-size: 13px; cursor: pointer; margin-top: 8px; box-shadow: 0 4px 14px rgba(2, 132, 199, 0.35); }}

  .data-table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  .data-table th {{ background: #F1F5F9; padding: 10px 14px; text-align: left; font-size: 11.5px; font-weight: 800; color: var(--text-secondary); text-transform: uppercase; border-bottom: 2px solid #E2E8F0; }}
  .data-table td {{ padding: 12px 14px; font-size: 12.5px; border-bottom: 1px solid #E2E8F0; color: var(--text-primary); }}
  .badge-active {{ background: #DCFCE7; color: #15803D; padding: 3px 8px; border-radius: 10px; font-size: 10.5px; font-weight: 800; }}
  .badge-inactive {{ background: #FEE2E2; color: #991B1B; padding: 3px 8px; border-radius: 10px; font-size: 10.5px; font-weight: 800; }}
  .btn-action-sm {{ padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; border: none; }}
  .btn-deactivate {{ background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; }}
  .btn-activate {{ background: #DCFCE7; color: #15803D; border: 1px solid #86EFAC; }}
  .btn-save-sm {{ background: #0284C7; color: white; }}
  .select-sm {{ padding: 4px 8px; border-radius: 6px; border: 1px solid #CBD5E1; font-size: 11.5px; font-weight: 700; }}
  .inline-form-group {{ display: flex; gap: 6px; align-items: center; }}

  .msg-banner {{ padding: 10px 14px; border-radius: 8px; font-size: 12px; font-weight: 700; margin-bottom: 16px; text-align: center; }}
  .msg-banner.success {{ background: #ECFDF5; color: #065F46; border: 1px solid #A7F3D0; }}
  .msg-banner.error {{ background: #FEF2F2; color: #991B1B; border: 1px solid #FECACA; }}
</style>
</head>
<body>

<header>
  <div class="header-brand">
    <div class="brand-logo-badge">SINFRA</div>
    <div class="brand-title-group">
      <h1>Relatório Semanal de Fiscalização de Obras</h1>
      <p>Tribunal de Justiça do Estado de Roraima — TJRR</p>
    </div>
  </div>

  <div class="header-user">
    <div class="user-badge-card">
      <div class="user-avatar">{USER_AVATAR}</div>
      <div class="user-info-text">
        <strong>{USER_NOME}</strong>
        <span>Login: {USER_LOGIN} <span class="role-pill">{USER_PERFIL_DISPLAY}</span></span>
      </div>
    </div>
    <a href="/logout" class="btn-logout">Encerrar Sessão</a>
  </div>
</header>

<div class="app-container">
  <aside>
    <div>
      <div class="sidebar-section-title">Obra em Fiscalização</div>
      <div class="select-work-card">
        <label>Selecionar Obra Ativa</label>
        <select class="work-dropdown" onchange="window.location.href='/dashboard?obra_id=' + this.value">
          {OBRAS_DROPDOWN_OPTIONS}
        </select>
        <div class="work-meta-badge">
          <span>Contrato: {ACTIVE_OBRA_CONTRATO}</span>
        </div>
      </div>
    </div>

    <div>
      <div class="sidebar-section-title">Módulos do Sistema</div>
      <ul class="nav-menu">
        {SIDEBAR_NAV_MENU_HTML}
      </ul>
    </div>
  </aside>

  <main>
    {MSG_BANNER_HTML}

    <!-- MÓDULO 1: VISÃO GERAL (DASHBOARD) -->
    <div id="module-dashboard" class="module-view {MOD_DASH_ACTIVE}">
      <div class="overview-header-card">
        <div class="overview-header-title">
          <h2>{ACTIVE_OBRA_NOME}</h2>
          <p>Acompanhamento executivo de prazos e fiscalização de obras públicas</p>
        </div>
        <div class="update-tag">
          <span>🟢</span> Fiscal Responsável: <strong>{ACTIVE_OBRA_FISCAL_NOME}</strong>
        </div>
      </div>

      <!-- Barra de Progresso do Prazo -->
      <div class="progress-card">
        <div class="progress-card-header">
          <span class="progress-card-title">⏱️ Tempo Decorrido do Contrato & Cronograma</span>
          <span class="progress-card-perc">{ACTIVE_OBRA_PCT_PRAZO}% do Prazo Consumido</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" style="width: {ACTIVE_OBRA_PCT_PRAZO}%;"></div>
        </div>
        <div class="timeline-grid">
          <div class="timeline-item">
            <span>Início da Obra</span>
            <strong>{ACTIVE_OBRA_PRAZO_INICIO}</strong>
          </div>
          <div class="timeline-item">
            <span>Prazo Consumido</span>
            <strong>{ACTIVE_OBRA_DIAS_DECORRIDOS} de {ACTIVE_OBRA_DIAS_TOTAIS} dias</strong>
          </div>
          <div class="timeline-item">
            <span>Término Previsto</span>
            <strong>{ACTIVE_OBRA_PRAZO_FIM}</strong>
          </div>
        </div>
      </div>

      <div class="details-grid">
        <!-- Card 1: Identificação da Obra -->
        <div class="section-card">
          <h3 class="section-card-title">📄 1. Identificação da Obra</h3>
          <table class="info-table">
            <tr><td class="info-label">Obra Acompanhada</td><td class="info-val">{ACTIVE_OBRA_NOME}</td></tr>
            <tr><td class="info-label">Endereço Completo</td><td class="info-val">{ACTIVE_OBRA_ENDERECO}</td></tr>
            <tr><td class="info-label">Nº do Contrato</td><td class="info-val"><strong>{ACTIVE_OBRA_CONTRATO}</strong></td></tr>
            <tr><td class="info-label">Nº da OS</td><td class="info-val"><strong>{ACTIVE_OBRA_OS}</strong></td></tr>
            <tr><td class="info-label">Processo SEI</td><td class="info-val">{ACTIVE_OBRA_SEI}</td></tr>
            <tr><td class="info-label">Empresa Licitada</td><td class="info-val">{ACTIVE_OBRA_EMPREITEIRA}</td></tr>
            <tr><td class="info-label">Fiscal Responsável</td><td class="info-val">{ACTIVE_OBRA_FISCAL_NOME}</td></tr>
          </table>
        </div>

        <!-- Card 2: Atividades Realizadas na Semana -->
        <div class="section-card">
          <h3 class="section-card-title">🏗️ 2. Atividades Realizadas na Semana Atual</h3>
          <ul class="checklist-list">
            {CHECKLIST_ITEMS_HTML}
          </ul>

          <div class="history-box">
            <h4>📋 Atividades da Semana Passada (Histórico Anterior)</h4>
            <p>{ACTIVE_OBRA_HISTORICO_ANTERIOR}</p>
          </div>
        </div>
      </div>

      <div class="export-bar-card">
        <div>
          <h3 style="font-size:16px; font-weight:800;">📄 Relatório v68 Arredondado para Magistrados em PDF</h3>
          <p style="font-size:12px; color:#94A3B8; margin-top:2px;">Download em modelo v68 com caixas, réguas e tabelas arredondadas.</p>
        </div>
        <a href="/pdf?obra_id={ACTIVE_OBRA_ID}" class="btn-pdf-primary">📥 Baixar PDF v68 Limpo</a>
      </div>
    </div>

    <!-- MÓDULO 2: EDITAR DADOS DA SEMANA -->
    <div id="module-editar" class="module-view {MOD_EDIT_ACTIVE}">
      <div class="section-card">
        <h3 class="section-card-title">✏️ Editar Informações da Obra e Atividades da Semana</h3>
        {PERMISSAO_EDITAR_BANNER}
        <form action="/salvar_obra" method="POST">
          <input type="hidden" name="obra_id" value="{ACTIVE_OBRA_ID}">
          <div class="form-grid">
            <div class="form-group form-group-full">
              <label>Nome Oficial da Obra</label>
              <input type="text" name="nome" value="{ACTIVE_OBRA_NOME}" {CAN_EDIT_ATTR} required>
            </div>
            <div class="form-group">
              <label>Endereço Completo</label>
              <input type="text" name="endereco" value="{ACTIVE_OBRA_ENDERECO}" {CAN_EDIT_ATTR} required>
            </div>
            <div class="form-group">
              <label>Empresa Executora Licitada</label>
              <input type="text" name="empreiteira" value="{ACTIVE_OBRA_EMPREITEIRA}" {CAN_EDIT_ATTR} required>
            </div>
            <div class="form-group">
              <label>Nº do Contrato</label>
              <input type="text" name="contrato" value="{ACTIVE_OBRA_CONTRATO}" {CAN_EDIT_ATTR} required>
            </div>
            <div class="form-group">
              <label>Nº da Ordem de Serviço (OS)</label>
              <input type="text" name="ordem_servico" value="{ACTIVE_OBRA_OS}" {CAN_EDIT_ATTR} required>
            </div>
            <div class="form-group">
              <label>Processo SEI</label>
              <input type="text" name="processo_sei" value="{ACTIVE_OBRA_SEI}" {CAN_EDIT_ATTR} required>
            </div>
            <div class="form-group">
              <label>Fiscal Responsável Designado {FISCAL_ADMIN_ONLY_LABEL}</label>
              {FISCAL_INPUT_OR_SELECT_HTML}
            </div>

            <div class="form-group form-group-full">
              <label>Atividades Realizadas na Semana Atual (Digite uma por linha)</label>
              <textarea name="atividades" rows="4" {CAN_EDIT_ATTR}>{ACTIVE_OBRA_ATIVIDADES_RAW}</textarea>
            </div>

            <div class="form-group form-group-full">
              <label>Atividades da Semana Passada / Histórico Anterior (Digite uma por linha ou texto livre)</label>
              <textarea name="historico_anterior" rows="4" {CAN_EDIT_ATTR}>{ACTIVE_OBRA_HISTORICO_RAW}</textarea>
            </div>
          </div>
          {SUBMIT_SAVE_BTN_HTML}
        </form>
      </div>
    </div>

    <!-- MÓDULO 3: PASTA DE ARQUIVOS DA OBRA -->
    <div id="module-arquivos" class="module-view {MOD_ARQ_ACTIVE}">
      <div class="section-card">
        <h3 class="section-card-title">📁 Pasta da Obra: Repositório de Relatórios Arquivados</h3>
        <p style="font-size: 12.5px; color: var(--text-secondary); margin-bottom: 14px;">Histórico permanente de relatórios gerados e armazenados no banco de dados.</p>
        <table class="data-table">
          <thead>
            <tr>
              <th>Código / Relatório</th>
              <th>Período de Referência</th>
              <th>Fiscal Responsável</th>
              <th>Status</th>
              <th>Ações</th>
            </tr>
          </thead>
          <tbody>
            {REPOSITORIO_RELATORIOS_ROWS}
          </tbody>
        </table>
      </div>
    </div>

    <!-- MÓDULO 4: AUDITORIA & SEGURANÇA -->
    <div id="module-auditoria" class="module-view {MOD_AUD_ACTIVE}">
      <div class="section-card">
        <h3 class="section-card-title">🛡️ Log de Auditoria & Trilha de Segurança</h3>
        <p style="font-size: 12.5px; color: var(--text-secondary); margin-bottom: 14px;">Registro de downloads de relatórios e eventos do sistema.</p>
        <table class="data-table">
          <thead>
            <tr>
              <th>Data / Hora</th>
              <th>Usuário</th>
              <th>Ação Realizada</th>
              <th>Detalhes do Evento</th>
            </tr>
          </thead>
          <tbody>
            {LOGS_AUDITORIA_ROWS}
          </tbody>
        </table>
      </div>
    </div>

    <!-- MÓDULO 5: GESTÃO DE USUÁRIOS & OBRAS (EXCLUSIVO ADMIN) -->
    <div id="module-admin" class="module-view {MOD_ADM_ACTIVE}">
      {ADMIN_MODULE_CONTENT_HTML}
    </div>

    <!-- MÓDULO 6: GESTÃO DE SENHAS (EXCLUSIVO ADMIN) -->
    <div id="module-passwords" class="module-view {MOD_PASS_ACTIVE}">
      {PASS_MODULE_CONTENT_HTML}
    </div>
  </main>
</div>

<script>
  function switchModule(modName, btnEl) {{
    document.querySelectorAll('.module-view').forEach(function(view) {{
      view.classList.remove('active');
    }});
    document.querySelectorAll('.nav-item-btn').forEach(function(btn) {{
      btn.classList.remove('active');
    }});

    var targetMod = document.getElementById('module-' + modName);
    if (targetMod) {{
      targetMod.classList.add('active');
    }}
    if (btnEl) {{
      btnEl.classList.add('active');
    }}
  }}
</script>

</body>
</html>
"""

# =========================================================================
# SERVIDOR HTTP & ROTAS DO SISTEMA
# =========================================================================
class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

class SinfraHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    def get_cookie_user(self):
        cookie_header = self.headers.get('Cookie', '')
        if 'session_login=' in cookie_header:
            try:
                login = cookie_header.split('session_login=')[1].split(';')[0].strip()
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM usuarios WHERE login = ? AND ativo = 1", (login,))
                user = cursor.fetchone()
                conn.close()
                if user:
                    return dict(user)
            except Exception:
                pass
        return None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        msg = query.get('msg', [''])[0]
        tab = query.get('tab', ['login'])[0]
        email_req = query.get('email', [''])[0]

        user = self.get_cookie_user()

        # Rota LOGOUT
        if path == "/logout":
            self.send_response(302)
            self.send_header('Set-Cookie', 'session_login=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT')
            self.send_header('Location', '/?msg=' + urllib.parse.quote('Sessão encerrada com segurança.'))
            self.end_headers()
            return

        # Rota GERAR PDF REAL (MODELO V68 ARREDONDADO)
        if path == "/pdf":
            obra_id = query.get('obra_id', ['1'])[0]
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM obras WHERE id = ?", (obra_id,))
            obra_row = cursor.fetchone()
            conn.close()

            if obra_row:
                obra_dict = dict(obra_row)
                atividades = json.loads(obra_dict.get('atividades_json') or '[]')
                historico = obra_dict.get('historico_anterior') or ''

                pdf_bytes = generate_pdf_bytes(obra_dict, atividades, historico)

                u_name = user['login'] if user else 'Visitante'
                conn_log = get_db()
                agora_str = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
                conn_log.execute("INSERT INTO logs_auditoria (data_hora, usuario, acao, detalhes) VALUES (?, ?, ?, ?)",
                                 (agora_str, u_name, "DOWNLOAD_PDF", f"Relatório v68 Arredondado da Obra #{obra_id} ({obra_dict['nome']})"))
                conn_log.commit()
                conn_log.close()

                self.send_response(200)
                self.send_header("Content-type", "application/pdf")
                self.send_header("Content-Disposition", f"attachment; filename=Relatorio_SINFRA_v68_Obra_{obra_id}.pdf")
                self.end_headers()
                self.wfile.write(pdf_bytes)
                return

        # Rota DASHBOARD / HOME
        if path == "/dashboard" or path == "/":
            if not user and path == "/dashboard":
                self.send_response(302)
                self.send_header('Location', '/?msg=' + urllib.parse.quote('Sua sessão expirou. Faça login novamente.') + '&tab=login')
                self.end_headers()
                return

            if not user:
                msg_banner_html = ""
                if msg:
                    banner_type = "error" if ("Erro" in msg or "expirou" in msg or "Incorret" in msg) else "success"
                    msg_banner_html = f'<div class="msg-banner {banner_type}">{esc(msg)}</div>'

                tab_login_active = "active" if tab == "login" else ""
                tab_criar_active = "active" if tab == "criar-conta" else ""
                tab_esqueci_active = "active" if tab == "esqueci-senha" else ""

                login_html = LOGIN_HTML_TEMPLATE.format(
                    MSG_BANNER_HTML=msg_banner_html,
                    TAB_LOGIN_ACTIVE=tab_login_active,
                    TAB_CRIAR_ACTIVE=tab_criar_active
                )

                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(login_html.encode('utf-8'))
                return

            # Exibir Dashboard
            conn = get_db()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM obras ORDER BY id ASC")
            todas_obras = [dict(r) for r in cursor.fetchall()]

            selected_obra_id = int(query.get('obra_id', [todas_obras[0]['id'] if todas_obras else 1])[0])
            active_obra = next((o for o in todas_obras if o['id'] == selected_obra_id), todas_obras[0] if todas_obras else {})

            cursor.execute("SELECT * FROM usuarios ORDER BY id ASC")
            todos_usuarios = [dict(r) for r in cursor.fetchall()]
            fiscais_list = [u for u in todos_usuarios if u['perfil'] in ('fiscal', 'admin') and u['ativo'] == 1]

            cursor.execute("SELECT * FROM relatorios_semanais WHERE obra_id = ? ORDER BY id DESC", (active_obra.get('id', 1),))
            relatorios_salvos = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM logs_auditoria ORDER BY id DESC LIMIT 20")
            logs_auditoria = [dict(r) for r in cursor.fetchall()]

            conn.close()

            user_perfil = user.get('perfil', 'visualizador').lower()
            is_admin = (user_perfil == 'admin')
            is_fiscal = (user_perfil == 'fiscal')
            is_assigned_fiscal = (user.get('id') == active_obra.get('fiscal_id')) or (user.get('login') == active_obra.get('fiscal_nome'))
            can_edit = is_admin or (is_fiscal and is_assigned_fiscal)

            active_module = query.get('module', ['dashboard'])[0]
            if user_perfil in ('visualizador', 'leitor') and active_module != 'dashboard':
                active_module = 'dashboard'
            elif is_fiscal and active_module == 'admin':
                active_module = 'dashboard'

            nav_dash_act = "active" if active_module == "dashboard" else ""
            nav_edit_act = "active" if active_module == "editar" else ""
            nav_arq_act = "active" if active_module == "arquivos" else ""
            nav_aud_act = "active" if active_module == "auditoria" else ""
            nav_adm_act = "active" if active_module == "admin" else ""
            nav_pass_act = "active" if active_module == "passwords" else ""

            sidebar_nav_menu_html = f'<li><button class="nav-item-btn {nav_dash_act}" onclick="switchModule(\'dashboard\', this)"><span class="nav-icon">📊</span> Visão Geral (Dashboard)</button></li>'

            if is_admin or is_fiscal:
                sidebar_nav_menu_html += f'<li><button class="nav-item-btn {nav_edit_act}" onclick="switchModule(\'editar\', this)"><span class="nav-icon">✏️</span> Editar Dados da Semana</button></li>'
                sidebar_nav_menu_html += f'<li><button class="nav-item-btn {nav_arq_act}" onclick="switchModule(\'arquivos\', this)"><span class="nav-icon">📁</span> Pasta de Arquivos da Obra</button></li>'
                sidebar_nav_menu_html += f'<li><button class="nav-item-btn {nav_aud_act}" onclick="switchModule(\'auditoria\', this)"><span class="nav-icon">🛡️</span> Auditoria & Segurança</button></li>'

            if is_admin:
                sidebar_nav_menu_html += f'<li><button class="nav-item-btn {nav_adm_act}" onclick="switchModule(\'admin\', this)"><span class="nav-icon">⚙️</span> Módulo 5: Gestão de Obras & Usuários</button></li>'
                sidebar_nav_menu_html += f'<li><button class="nav-item-btn {nav_pass_act}" onclick="switchModule(\'passwords\', this)"><span class="nav-icon">🔑</span> Módulo 6: Gestão de Senhas (Admin)</button></li>' 

            msg_banner_html = ""
            if msg:
                banner_type = "error" if "Erro" in msg else "success"
                msg_banner_html = f'<div class="msg-banner {banner_type}">{esc(msg)}</div>'

            obras_dropdown_options = ""
            for ob in todas_obras:
                st_tag = "" if ob.get('ativa', 1) == 1 else " [INATIVA]"
                sel = 'selected' if ob['id'] == active_obra.get('id') else ''
                obras_dropdown_options += f'<option value="{ob["id"]}" {sel}>{esc(ob["nome"])}{st_tag}</option>'

            atividades_list = json.loads(active_obra.get('atividades_json') or '[]')
            checklist_items_html = ""
            if atividades_list:
                for act in atividades_list:
                    checklist_items_html += f'<li class="check-item"><span class="check-badge">✓</span> {esc(act)}</li>'
            else:
                checklist_items_html = '<li class="check-item">Nenhuma atividade registrada para esta semana.</li>'

            atividades_raw_str = "\n".join(atividades_list)
            historico_raw_str = str(active_obra.get('historico_anterior') or '')

            if can_edit:
                permissao_editar_banner = '<div style="background:#ECFDF5; color:#065F46; border:1px solid #A7F3D0; padding:10px 14px; border-radius:8px; font-size:12px; font-weight:700; margin-bottom:16px;">✅ Você possui permissão para editar os dados desta obra.</div>'
                can_edit_attr = ""
                submit_save_btn_html = '<button type="submit" class="btn-save-submit">💾 Salvar Alterações no Banco de Dados</button>'
            else:
                permissao_editar_banner = '<div style="background:#FFFBEB; color:#92400E; border:1px solid #FCD34D; padding:10px 14px; border-radius:8px; font-size:12px; font-weight:700; margin-bottom:16px;">🔒 Modo Leitura: Apenas o Fiscal Responsável designado ou um Administrador pode editar esta obra.</div>'
                can_edit_attr = "readonly disabled"
                submit_save_btn_html = '<button type="button" class="btn-save-submit" style="opacity:0.5; cursor:not-allowed;" disabled>🔒 Edição Restrita</button>'

            if is_admin:
                fiscal_admin_only_label = ' <span style="color:#0284C7; font-size:11px;">(Exclusivo Administrador)</span>'
                fiscal_options = ""
                for f_u in fiscais_list:
                    sel_f = 'selected' if f_u['id'] == active_obra.get('fiscal_id') else ''
                    fiscal_options += f'<option value="{f_u["id"]}" {sel_f}>{esc(f_u["nome"])} ({f_u["login"]})</option>'
                fiscal_input_or_select_html = f'<select name="fiscal_id" class="form-input">{fiscal_options}</select>'
            else:
                fiscal_admin_only_label = ' <span style="color:#64748B; font-size:11px;">🔒 (Restrito — Apenas Administradores podem reatribuir)</span>'
                fiscal_input_or_select_html = f'<input type="text" value="{esc(active_obra.get("fiscal_nome", ""))}" readonly disabled>'

            repositorio_relatorios_rows = ""
            if relatorios_salvos:
                for rel in relatorios_salvos:
                    repositorio_relatorios_rows += f'''
                    <tr>
                      <td><strong>{esc(rel['codigo_relatorio'])}</strong></td>
                      <td>{esc(rel['periodo_ref'])}</td>
                      <td>{esc(rel['fiscal_nome'])}</td>
                      <td><span class="badge-active">Arquivado</span></td>
                      <td><a href="/pdf?obra_id={active_obra.get('id', 1)}" class="btn-action-sm btn-save-sm" style="text-decoration:none;">📄 Baixar PDF</a></td>
                    </tr>
                    '''
            else:
                repositorio_relatorios_rows = '''
                <tr>
                  <td><strong>REL-2026-W01</strong></td>
                  <td>Semana Atual</td>
                  <td>Administrador SINFRA</td>
                  <td><span class="badge-active">Arquivado</span></td>
                  <td><a href="/pdf?obra_id=1" class="btn-action-sm btn-save-sm" style="text-decoration:none;">📄 Baixar PDF</a></td>
                </tr>
                '''

            logs_auditoria_rows = ""
            for lg in logs_auditoria:
                logs_auditoria_rows += f'''
                <tr>
                  <td>{esc(lg['data_hora'])}</td>
                  <td><strong>{esc(lg['usuario'])}</strong></td>
                  <td><code>{esc(lg['acao'])}</code></td>
                  <td>{esc(lg['detalhes'])}</td>
                </tr>
                '''

            if is_admin:
                admin_obras_rows = ""
                for ob in todas_obras:
                    st_badge = '<span class="badge-active">Ativa</span>' if ob.get('ativa', 1) == 1 else '<span class="badge-inactive">Inativa</span>'
                    btn_toggle_text = "Desativar Obra" if ob.get('ativa', 1) == 1 else "Ativar Obra"
                    btn_class = "btn-deactivate" if ob.get('ativa', 1) == 1 else "btn-activate"
                    admin_obras_rows += f'''
                    <tr>
                      <td><strong>#{ob['id']}</strong></td>
                      <td>{esc(ob['nome'])}</td>
                      <td>{esc(ob['contrato'])}</td>
                      <td>{esc(ob['fiscal_nome'])}</td>
                      <td>{st_badge}</td>
                      <td>
                        <form action="/toggle_status_obra" method="POST" style="display:inline;">
                          <input type="hidden" name="obra_id" value="{ob['id']}">
                          <button type="submit" class="btn-action-sm {btn_class}">{btn_toggle_text}</button>
                        </form>
                      </td>
                    </tr>
                    '''

                admin_users_rows = ""
                for u in todos_usuarios:
                    u_badge = '<span class="badge-active">Ativo</span>' if u.get('ativo', 1) == 1 else '<span class="badge-inactive">Inativo</span>'
                    u_btn_text = "Desativar" if u.get('ativo', 1) == 1 else "Ativar"
                    u_btn_class = "btn-deactivate" if u.get('ativo', 1) == 1 else "btn-activate"

                    curr_p = u.get('perfil', 'visualizador').lower()
                    sel_vis = 'selected' if curr_p == 'visualizador' else ''
                    sel_fisc = 'selected' if curr_p == 'fiscal' else ''
                    sel_adm = 'selected' if curr_p == 'admin' else ''

                    admin_users_rows += f'''
                    <tr>
                      <td><strong>{esc(u['login'])}</strong></td>
                      <td>{esc(u['nome'])}</td>
                      <td>{esc(u['email'])}</td>
                      <td>
                        <form action="/alterar_perfil_usuario" method="POST" class="inline-form-group">
                          <input type="hidden" name="user_id" value="{u['id']}">
                          <select name="novo_perfil" class="select-sm">
                            <option value="visualizador" {sel_vis}>Visualizador</option>
                            <option value="fiscal" {sel_fisc}>Fiscal</option>
                            <option value="admin" {sel_adm}>Administrador</option>
                          </select>
                          <button type="submit" class="btn-action-sm btn-save-sm">Alterar Perfil</button>
                        </form>
                      </td>
                      <td>{u_badge}</td>
                      <td>
                        <form action="/toggle_status_usuario" method="POST" style="display:inline;">
                          <input type="hidden" name="user_id" value="{u['id']}">
                          <button type="submit" class="btn-action-sm {u_btn_class}">{u_btn_text}</button>
                        </form>
                      </td>
                    </tr>
                    '''

                fiscais_select_opts = ""
                for f_u in fiscais_list:
                    fiscais_select_opts += f'<option value="{f_u["id"]}">{esc(f_u["nome"])} ({f_u["login"]})</option>'

                admin_module_content_html = f'''
                <div class="section-card">
                  <h3 class="section-card-title">➕ Cadastrar Nova Obra / Empreitada (Exclusivo Administrador)</h3>
                  <form action="/cadastrar_obra" method="POST">
                    <div class="form-grid">
                      <div class="form-group form-group-full">
                        <label>Nome Oficial da Obra</label>
                        <input type="text" name="nome" placeholder="Ex: Construção do Fórum da Comarca de Caracaraí" required>
                      </div>
                      <div class="form-group">
                        <label>Endereço Completo</label>
                        <input type="text" name="endereco" placeholder="Ex: Av. Dr. Zanny, nº 100 - Caracaraí - RR" required>
                      </div>
                      <div class="form-group">
                        <label>Empresa Executora Licitada</label>
                        <input type="text" name="empreiteira" placeholder="Ex: Roraima Engenharia EIRELI" required>
                      </div>
                      <div class="form-group">
                        <label>Nº do Contrato</label>
                        <input type="text" name="contrato" placeholder="Ex: Contrato nº 22/2026 - TJRR" required>
                      </div>
                      <div class="form-group">
                        <label>Nº da Ordem de Serviço (OS)</label>
                        <input type="text" name="ordem_servico" placeholder="Ex: OS nº 005/2026-SINFRA" required>
                      </div>
                      <div class="form-group">
                        <label>Processo SEI</label>
                        <input type="text" name="processo_sei" placeholder="Ex: 0014500-12.2026.8.23.8000" required>
                      </div>
                      <div class="form-group">
                        <label>Fiscal Responsável Designado</label>
                        <select name="fiscal_id" class="form-input" required>
                          {fiscais_select_opts}
                        </select>
                      </div>
                      <div class="form-group">
                        <label>Data de Início do Prazo</label>
                        <input type="date" name="prazo_inicio" value="2026-07-01" required>
                      </div>
                      <div class="form-group form-group-full">
                        <label>Data de Término Previsto</label>
                        <input type="date" name="prazo_fim" value="2027-08-16" required>
                      </div>
                    </div>
                    <button type="submit" class="btn-save-submit">🏗️ Salvar e Cadastrar Nova Obra</button>
                  </form>
                </div>

                <div class="section-card">
                  <h3 class="section-card-title">🏢 Gestão de Obras & Empreitadas (Ativar / Desativar)</h3>
                  <table class="data-table">
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>Nome da Obra</th>
                        <th>Contrato</th>
                        <th>Fiscal Responsável</th>
                        <th>Status</th>
                        <th>Ações</th>
                      </tr>
                    </thead>
                    <tbody>
                      {admin_obras_rows}
                    </tbody>
                  </table>
                </div>

                <div class="section-card">
                  <h3 class="section-card-title">👥 Gestão de Usuários & Alteração de Perfis (Tipo de Conta)</h3>
                  <p style="font-size: 12.5px; color: var(--text-secondary); margin-bottom: 14px;">Toda nova conta criada nasce como <strong>Visualizador</strong>. Altere o perfil para Fiscal ou Administrador para conceder permissões de edição.</p>
                  <table class="data-table">
                    <thead>
                      <tr>
                        <th>Login</th>
                        <th>Nome Completo</th>
                        <th>E-mail Funcional</th>
                        <th>Alterar Perfil (Tipo de Conta)</th>
                        <th>Status</th>
                        <th>Ações</th>
                      </tr>
                    </thead>
                    <tbody>
                      {admin_users_rows}
                    </tbody>
                  </table>
                </div>
                '''
            else:
                admin_module_content_html = '''
                <div class="section-card">
                  <h3 class="section-card-title">🔒 Acesso Restrito ao Administrador</h3>
                  <p style="font-size:13.5px; color:var(--text-secondary);">Apenas usuários com perfil de Administrador possuem permissão para cadastrar obras, reatribuir fiscais e gerenciar contas de usuários.</p>
                </div>
                '''

            dt_inicio = str(active_obra.get('prazo_inicio', '2026-07-01'))
            dt_fim = str(active_obra.get('prazo_fim', '2027-08-16'))
            try:
                d1 = datetime.datetime.strptime(dt_inicio, "%Y-%m-%d")
                d2 = datetime.datetime.strptime(dt_fim, "%Y-%m-%d")
                hoje = datetime.datetime.now()
                tot_dias = max((d2 - d1).days, 1)
                dec_dias = max(min((hoje - d1).days, tot_dias), 0)
                pct_prazo = min(max(int((dec_dias / tot_dias) * 100), 0), 100)
                dt_inicio_str = d1.strftime("%d/%m/%Y")
                dt_fim_str = d2.strftime("%d/%m/%Y")
            except Exception:
                dt_inicio_str, dt_fim_str = "01/07/2026", "16/08/2027"
                pct_prazo, dec_dias, tot_dias = 20, 83, 411

            nav_pass_act = "active" if active_module == "passwords" else ""
            mod_dash_act = "active" if active_module == "dashboard" else ""
            mod_edit_act = "active" if active_module == "editar" else ""
            mod_arq_act = "active" if active_module == "arquivos" else ""
            mod_aud_act = "active" if active_module == "auditoria" else ""
            mod_adm_act = "active" if active_module == "admin" else ""
            mod_pass_act = "active" if active_module == "passwords" else ""

            if is_admin:
                users_pass_select_opts = ""
                for u_p in todos_usuarios:
                    users_pass_select_opts += f'<option value="{u_p["id"]}">{esc(u_p["nome"])} ({esc(u_p["login"])}) — {esc(u_p["email"])}</option>'

                pass_module_content_html = f'''
                <div class="section-card">
                  <h3 class="section-card-title">🔑 Módulo 6: Gestão e Redefinição de Senhas (Exclusivo Administrador)</h3>
                  <p style="font-size: 12.5px; color: var(--text-secondary); margin-bottom: 16px;">Como Administrador do SINFRA, você pode alterar a senha de acesso de qualquer usuário cadastrado no sistema em caso de esquecimento.</p>
                  <form action="/redefinir_senha_admin" method="POST" style="max-width: 500px;">
                    <div class="form-group" style="margin-bottom: 16px;">
                      <label style="display:block; font-weight:700; margin-bottom:6px; font-size:12.5px; color:var(--text-primary);">Selecionar Usuário Cadastrado</label>
                      <select name="user_id" class="form-input" style="width:100%; padding:9px 12px; border-radius:6px; border:1px solid var(--border);" required>
                        {users_pass_select_opts}
                      </select>
                    </div>
                    <div class="form-group" style="margin-bottom: 20px;">
                      <label style="display:block; font-weight:700; margin-bottom:6px; font-size:12.5px; color:var(--text-primary);">Nova Senha para a Conta</label>
                      <input type="password" name="nova_senha" class="form-input" style="width:100%; padding:9px 12px; border-radius:6px; border:1px solid var(--border);" placeholder="Digite a nova senha desejada" required>
                    </div>
                    <button type="submit" class="btn-save-submit" style="background:#0284C7; color:white; padding:10px 18px; border:none; border-radius:6px; font-weight:700; cursor:pointer;">🔑 Redefinir Senha do Usuário</button>
                  </form>
                </div>
                '''
            else:
                pass_module_content_html = '''
                <div class="section-card">
                  <h3 class="section-card-title">🔒 Acesso Restrito ao Administrador</h3>
                  <p style="font-size:13.5px; color:var(--text-secondary);">Apenas usuários com perfil de Administrador possuem permissão para redefinir senhas de contas no sistema.</p>
                </div>
                '''

            dashboard_html = DASHBOARD_HTML_TEMPLATE.format(
                USER_AVATAR=user['nome'][0].upper() if user.get('nome') else 'A',
                USER_NOME=esc(user.get('nome', 'Usuário SINFRA')),
                USER_LOGIN=esc(user.get('login', '')),
                USER_PERFIL_DISPLAY=esc(user.get('perfil', 'visualizador').capitalize()),
                OBRAS_DROPDOWN_OPTIONS=obras_dropdown_options,
                ACTIVE_OBRA_ID=active_obra.get('id', 1),
                ACTIVE_OBRA_CONTRATO=esc(active_obra.get('contrato', '')),
                ACTIVE_OBRA_NOME=esc(active_obra.get('nome', '')),
                ACTIVE_OBRA_ENDERECO=esc(active_obra.get('endereco', '')),
                ACTIVE_OBRA_EMPREITEIRA=esc(active_obra.get('empreiteira', '')),
                ACTIVE_OBRA_OS=esc(active_obra.get('ordem_servico', '')),
                ACTIVE_OBRA_SEI=esc(active_obra.get('processo_sei', '')),
                ACTIVE_OBRA_FISCAL_NOME=esc(active_obra.get('fiscal_nome', '')),
                ACTIVE_OBRA_PRAZO_INICIO=dt_inicio_str,
                ACTIVE_OBRA_PRAZO_FIM=dt_fim_str,
                ACTIVE_OBRA_PCT_PRAZO=pct_prazo,
                ACTIVE_OBRA_DIAS_DECORRIDOS=dec_dias,
                ACTIVE_OBRA_DIAS_TOTAIS=tot_dias,
                ACTIVE_OBRA_ATIVIDADES_RAW=esc(atividades_raw_str),
                ACTIVE_OBRA_HISTORICO_RAW=esc(historico_raw_str),
                ACTIVE_OBRA_HISTORICO_ANTERIOR=esc(historico_raw_str or 'Sem registros de histórico anterior.'),
                CHECKLIST_ITEMS_HTML=checklist_items_html,
                PERMISSAO_EDITAR_BANNER=permissao_editar_banner,
                CAN_EDIT_ATTR=can_edit_attr,
                SUBMIT_SAVE_BTN_HTML=submit_save_btn_html,
                FISCAL_ADMIN_ONLY_LABEL=fiscal_admin_only_label,
                FISCAL_INPUT_OR_SELECT_HTML=fiscal_input_or_select_html,
                REPOSITORIO_RELATORIOS_ROWS=repositorio_relatorios_rows,
                LOGS_AUDITORIA_ROWS=logs_auditoria_rows,
                SIDEBAR_NAV_MENU_HTML=sidebar_nav_menu_html,
                ADMIN_MODULE_CONTENT_HTML=admin_module_content_html,
                PASS_MODULE_CONTENT_HTML=pass_module_content_html,
                MOD_PASS_ACTIVE=mod_pass_act,
                MOD_DASH_ACTIVE=mod_dash_act,
                MOD_EDIT_ACTIVE=mod_edit_act,
                MOD_ARQ_ACTIVE=mod_arq_act,
                MOD_AUD_ACTIVE=mod_aud_act,
                MOD_ADM_ACTIVE=mod_adm_act,
                MSG_BANNER_HTML=msg_banner_html
            )

            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(dashboard_html.encode('utf-8'))
            return

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        params = urllib.parse.parse_qs(post_data)

        user = self.get_cookie_user()
        user_perfil = user.get('perfil', 'visualizador').lower() if user else 'visualizador'
        is_admin = (user_perfil == 'admin')

        # ROTA EXCLUSIVA ADMIN: REDEFINIR SENHA DE USUARIO
        if self.path == "/redefinir_senha_admin":
            if not user or not is_admin:
                self.send_response(302)
                self.send_header('Location', '/?msg=' + urllib.parse.quote('Erro: Permissão negada.') + '&tab=login')
                self.end_headers()
                return

            target_user_id = params.get('user_id', [''])[0].strip()
            nova_senha = params.get('nova_senha', [''])[0].strip()

            if target_user_id and nova_senha:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM usuarios WHERE id = ?", (target_user_id,))
                t_user = cursor.fetchone()

                if t_user:
                    t_login = t_user['login']
                    salt = secrets.token_hex(16)
                    senha_hash = hashlib.pbkdf2_hmac('sha256', nova_senha.encode(), salt.encode(), 100000).hex()

                    cursor.execute("UPDATE usuarios SET senha_hash = ?, salt = ? WHERE id = ?", (senha_hash, salt, target_user_id))
                    agora_str = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
                    cursor.execute("INSERT INTO logs_auditoria (data_hora, usuario, acao, detalhes) VALUES (?, ?, ?, ?)",
                                   (agora_str, user['login'], "REDEFINIR_SENHA_ADMIN", f"Senha do usuário '{t_login}' (ID #{target_user_id}) redefinida pelo Administrador."))
                    conn.commit()
                    conn.close()

                    self.send_response(302)
                    self.send_header('Location', '/dashboard?msg=' + urllib.parse.quote(f'Senha do usuário "{t_login}" alterada com sucesso pelo Administrador!') + '&mod=passwords')
                    self.end_headers()
                    return
                else:
                    conn.close()

            self.send_response(302)
            self.send_header('Location', '/dashboard?msg=' + urllib.parse.quote('Erro: Dados inválidos para alteração de senha.') + '&mod=passwords')
            self.end_headers()
            return

        # 1. ROTA POST /login
        if self.path == "/login":
            usuario_input = params.get('usuario', [''])[0].strip()
            senha_input = params.get('senha', [''])[0].strip()

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM usuarios WHERE (login = ? OR email = ?) AND ativo = 1", (usuario_input, usuario_input))
            u_row = cursor.fetchone()
            conn.close()

            if u_row:
                u_dict = dict(u_row)
                key_check = hashlib.pbkdf2_hmac('sha256', senha_input.encode(), u_dict['salt'].encode(), 100000).hex()
                if secrets.compare_digest(key_check, u_dict['senha_hash']):
                    conn_log = get_db()
                    agora_str = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
                    conn_log.execute("INSERT INTO logs_auditoria (data_hora, usuario, acao, detalhes) VALUES (?, ?, ?, ?)",
                                     (agora_str, u_dict['login'], "LOGIN_SUCESSO", f"Acesso efetuado com perfil {u_dict['perfil']}"))
                    conn_log.commit()
                    conn_log.close()

                    self.send_response(302)
                    self.send_header('Set-Cookie', f'session_login={u_dict["login"]}; Path=/; HttpOnly')
                    self.send_header('Location', '/dashboard?msg=' + urllib.parse.quote(f"Bem-vindo(a), {u_dict['nome']}!"))
                    self.end_headers()
                    return

            self.send_response(302)
            self.send_header('Location', '/?msg=' + urllib.parse.quote('Erro: Usuário ou senha incorretos.') + '&tab=login')
            self.end_headers()
            return

        # 2. ROTA POST /salvar_obra
        if self.path == "/salvar_obra":
            obra_id = int(params.get('obra_id', ['1'])[0])
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM obras WHERE id = ?", (obra_id,))
            obra_dict = dict(cursor.fetchone())

            is_assigned = (user.get('id') == obra_dict.get('fiscal_id')) or (user.get('login') == obra_dict.get('fiscal_nome'))
            if not (is_admin or (user_perfil == 'fiscal' and is_assigned)):
                conn.close()
                self.send_response(302)
                self.send_header('Location', f'/dashboard?obra_id={obra_id}&module=editar&msg=' + urllib.parse.quote('Erro: Você não possui permissão para editar esta obra.'))
                self.end_headers()
                return

            nome = params.get('nome', [obra_dict['nome']])[0].strip()
            endereco = params.get('endereco', [obra_dict['endereco']])[0].strip()
            empreiteira = params.get('empreiteira', [obra_dict['empreiteira']])[0].strip()
            contrato = params.get('contrato', [obra_dict['contrato']])[0].strip()
            ordem_servico = params.get('ordem_servico', [obra_dict['ordem_servico']])[0].strip()
            processo_sei = params.get('processo_sei', [obra_dict['processo_sei']])[0].strip()

            atividades_raw = params.get('atividades', [''])[0]
            novas_atividades_list = [a.strip() for a in atividades_raw.split('\n') if a.strip()]
            historico_anterior = params.get('historico_anterior', [''])[0].strip()

            fiscal_id = obra_dict['fiscal_id']
            fiscal_nome = obra_dict['fiscal_nome']
            if is_admin and 'fiscal_id' in params:
                new_fiscal_id = int(params['fiscal_id'][0])
                cursor.execute("SELECT * FROM usuarios WHERE id = ?", (new_fiscal_id,))
                f_u = cursor.fetchone()
                if f_u:
                    fiscal_id = f_u['id']
                    fiscal_nome = f_u['nome']

            cursor.execute("""
            UPDATE obras SET nome=?, endereco=?, empreiteira=?, contrato=?, ordem_servico=?, processo_sei=?, atividades_json=?, historico_anterior=?, fiscal_id=?, fiscal_nome=?
            WHERE id = ?
            """, (nome, endereco, empreiteira, contrato, ordem_servico, processo_sei, json.dumps(novas_atividades_list), historico_anterior, fiscal_id, fiscal_nome, obra_id))

            cod_rel = f"REL-{datetime.datetime.now().strftime('%Y-W%U')}"
            per_ref = datetime.datetime.now().strftime("%d/%m/%Y a %d/%m/%Y")
            cursor.execute("""
            INSERT INTO relatorios_semanais (obra_id, codigo_relatorio, periodo_ref, atividades_json, historico_anterior, fiscal_nome)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (obra_id, cod_rel, per_ref, json.dumps(novas_atividades_list), historico_anterior, fiscal_nome))

            agora_str = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
            cursor.execute("INSERT INTO logs_auditoria (data_hora, usuario, acao, detalhes) VALUES (?, ?, ?, ?)",
                           (agora_str, user['login'], "SALVAR_OBRA", f"Atualizados dados da Obra #{obra_id} ({nome})"))

            conn.commit()
            conn.close()

            self.send_response(302)
            self.send_header('Location', f'/dashboard?obra_id={obra_id}&module=dashboard&msg=' + urllib.parse.quote('Dados da obra e relatórios salvos com sucesso!'))
            self.end_headers()
            return

        # 3. ROTA ALTERAR PERFIL / TIPO DE CONTA (EXCLUSIVO ADMIN)
        if self.path == "/alterar_perfil_usuario":
            if not is_admin:
                self.send_response(302)
                self.send_header('Location', '/dashboard?module=admin&msg=' + urllib.parse.quote('Erro: Apenas Administradores podem alterar o tipo de conta.'))
                self.end_headers()
                return

            target_user_id = int(params.get('user_id', ['0'])[0])
            novo_perfil = params.get('novo_perfil', ['visualizador'])[0].strip().lower()

            if novo_perfil == 'admin':
                cargo = 'Administrador SINFRA'
            elif novo_perfil == 'fiscal':
                cargo = 'Engenheiro Fiscal de Obras'
            else:
                cargo = 'Visualizador SINFRA'

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE usuarios SET perfil = ?, cargo = ? WHERE id = ?", (novo_perfil, cargo, target_user_id))

            agora_str = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
            cursor.execute("INSERT INTO logs_auditoria (data_hora, usuario, acao, detalhes) VALUES (?, ?, ?, ?)",
                           (agora_str, user['login'], "ALTERAR_PERFIL", f"Perfil do Usuário ID #{target_user_id} alterado para {novo_perfil}"))

            conn.commit()
            conn.close()

            self.send_response(302)
            self.send_header('Location', '/dashboard?module=admin&msg=' + urllib.parse.quote(f'Perfil do usuário alterado para {novo_perfil.capitalize()} com sucesso!'))
            self.end_headers()
            return

        # 4. ROTA CADASTRAR NOVA OBRA (EXCLUSIVO ADMIN)
        if self.path == "/cadastrar_obra":
            if not is_admin:
                self.send_response(302)
                self.send_header('Location', '/dashboard?msg=' + urllib.parse.quote('Erro: Apenas Administradores podem cadastrar obras.'))
                self.end_headers()
                return

            nome = params.get('nome', [''])[0].strip()
            endereco = params.get('endereco', [''])[0].strip()
            empreiteira = params.get('empreiteira', [''])[0].strip()
            contrato = params.get('contrato', [''])[0].strip()
            ordem_servico = params.get('ordem_servico', [''])[0].strip()
            processo_sei = params.get('processo_sei', [''])[0].strip()
            fiscal_id = int(params.get('fiscal_id', [2])[0])
            prazo_inicio = params.get('prazo_inicio', ['2026-07-01'])[0].strip()
            prazo_fim = params.get('prazo_fim', ['2027-08-16'])[0].strip()

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM usuarios WHERE id = ?", (fiscal_id,))
            f_u = cursor.fetchone()
            fiscal_nome = f_u['nome'] if f_u else 'Administrador SINFRA'

            cursor.execute("""
            INSERT INTO obras (nome, endereco, empreiteira, contrato, ordem_servico, processo_sei, fiscal_id, fiscal_nome, prazo_inicio, prazo_fim, atividades_json, historico_anterior)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '')
            """, (nome, endereco, empreiteira, contrato, ordem_servico, processo_sei, fiscal_id, fiscal_nome, prazo_inicio, prazo_fim))

            new_obra_id = cursor.lastrowid

            agora_str = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
            cursor.execute("INSERT INTO logs_auditoria (data_hora, usuario, acao, detalhes) VALUES (?, ?, ?, ?)",
                           (agora_str, user['login'], "CADASTRAR_OBRA", f"Nova Obra cadastrada: #{new_obra_id} ({nome})"))

            conn.commit()
            conn.close()

            self.send_response(302)
            self.send_header('Location', f'/dashboard?obra_id={new_obra_id}&module=dashboard&msg=' + urllib.parse.quote(f'Nova obra "{nome}" cadastrada com sucesso!'))
            self.end_headers()
            return

        # 5. ROTA ATIVAR/DESATIVAR OBRA (EXCLUSIVO ADMIN)
        if self.path == "/toggle_status_obra":
            if not is_admin:
                self.send_response(302)
                self.send_header('Location', '/dashboard?msg=' + urllib.parse.quote('Erro: Apenas Administradores.'))
                self.end_headers()
                return

            obra_id = int(params.get('obra_id', ['0'])[0])
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT ativa FROM obras WHERE id = ?", (obra_id,))
            ob_row = cursor.fetchone()
            if ob_row:
                novo_st = 0 if ob_row['ativa'] == 1 else 1
                cursor.execute("UPDATE obras SET ativa = ? WHERE id = ?", (novo_st, obra_id))
                agora_str = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
                cursor.execute("INSERT INTO logs_auditoria (data_hora, usuario, acao, detalhes) VALUES (?, ?, ?, ?)",
                               (agora_str, user['login'], "TOGGLE_OBRA", f"Status da Obra #{obra_id} alterado para {novo_st}"))
                conn.commit()
            conn.close()

            self.send_response(302)
            self.send_header('Location', '/dashboard?module=admin&msg=' + urllib.parse.quote('Status da Obra alterado com sucesso!'))
            self.end_headers()
            return

        # 6. ROTA ATIVAR/DESATIVAR USUARIO (EXCLUSIVO ADMIN)
        if self.path == "/toggle_status_usuario":
            if not is_admin:
                self.send_response(302)
                self.send_header('Location', '/dashboard?msg=' + urllib.parse.quote('Erro: Apenas Administradores.'))
                self.end_headers()
                return

            user_id = int(params.get('user_id', ['0'])[0])
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT ativo FROM usuarios WHERE id = ?", (user_id,))
            u_row = cursor.fetchone()
            if u_row:
                novo_st = 0 if u_row['ativo'] == 1 else 1
                cursor.execute("UPDATE usuarios SET ativo = ? WHERE id = ?", (novo_st, user_id))
                agora_str = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
                cursor.execute("INSERT INTO logs_auditoria (data_hora, usuario, acao, detalhes) VALUES (?, ?, ?, ?)",
                               (agora_str, user['login'], "TOGGLE_USUARIO", f"Status do Perfil do Usuario ID #{user_id} alterado para {novo_st}"))
                conn.commit()
            conn.close()

            self.send_response(302)
            self.send_header('Location', '/dashboard?module=admin&msg=' + urllib.parse.quote('Status do perfil do usuário alterado com sucesso!'))
            self.end_headers()
            return

        # 7. ROTA CRIAR CONTA (PADRÃO VISUALIZADOR)
        if self.path == "/criar_conta":
            nome = params.get('nome', [''])[0].strip()
            email = params.get('email', [''])[0].strip()
            usuario = params.get('usuario', [''])[0].strip()
            senha = params.get('senha', [''])[0].strip()

            salt = secrets.token_hex(16)
            senha_hash = hashlib.pbkdf2_hmac('sha256', senha.encode(), salt.encode(), 100000).hex()

            try:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO usuarios (login, nome, email, senha_hash, salt, perfil, cargo, ativo)
                VALUES (?, ?, ?, ?, ?, 'visualizador', 'Visualizador SINFRA', 1)
                """, (usuario, nome, email, senha_hash, salt))
                conn.commit()
                conn.close()

                self.send_response(302)
                self.send_header('Location', '/?msg=' + urllib.parse.quote('Conta de Visualizador criada com sucesso! Faça seu login. (O Administrador poderá alterar seu perfil se necessário).') + '&tab=login')
                self.end_headers()
            except sqlite3.IntegrityError:
                self.send_response(302)
                self.send_header('Location', '/?msg=' + urllib.parse.quote('Erro: Nome de usuário ou e-mail já cadastrado no sistema.') + '&tab=criar-conta')
                self.end_headers()
            return

        


def start_server():
    port = int(os.environ.get("PORT", 8000))
    server_address = ("0.0.0.0", port)
    httpd = ReusableTCPServer(server_address, SinfraHTTPRequestHandler)
    print(f"Servidor SINFRA / TJRR (sinfra_v30) rodando em http://0.0.0.0:{port}")
    httpd.serve_forever()

if __name__ == "__main__":
    start_server()
