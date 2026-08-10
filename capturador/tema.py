"""Tema visual: fichas de design e geracao da folha de estilo.

Toda a aparencia sai das duas paletas abaixo. Para mudar as cores do aplicativo
inteiro basta editar `CLARO` e `ESCURO` — nenhum valor de cor aparece solto no
resto do codigo. As medidas (raio de canto, espacamento, altura de controle)
ficam em `METRICA` pelo mesmo motivo.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

AUTO, CLARO_, ESCURO_ = "auto", "claro", "escuro"

# A area de video fica escura nos dois temas: e o fundo neutro contra o qual a
# imagem capturada e julgada, e alternar isso mudaria a percepcao das cores.
LONA_VIDEO = "#0b0c0f"

CLARO = {
    "fundo": "#f2f3f5",
    "superficie": "#ffffff",
    "superficie_alta": "#f7f8fa",
    "borda": "#dcdfe5",
    "borda_forte": "#c3c8d1",
    "texto": "#1b1e23",
    "texto_suave": "#5f6570",
    "destaque": "#2f6fed",
    "destaque_texto": "#ffffff",
    "destaque_suave": "#e5edfd",
    "perigo": "#d32f38",
    "sucesso": "#2f8a46",
    "aviso": "#b0761a",
    "sombra": "rgba(0,0,0,0.06)",
}

ESCURO = {
    "fundo": "#15171c",
    "superficie": "#1d2026",
    "superficie_alta": "#252932",
    "borda": "#31363f",
    "borda_forte": "#434a56",
    "texto": "#e7e9ee",
    "texto_suave": "#98a0ad",
    "destaque": "#5b91ff",
    "destaque_texto": "#0d1117",
    "destaque_suave": "#1e2a44",
    "perigo": "#f0575f",
    "sucesso": "#4cb265",
    "aviso": "#e0a33a",
    "sombra": "rgba(0,0,0,0.35)",
}

METRICA = {
    "raio": 10,
    "raio_pequeno": 6,
    "altura_controle": 32,
    "espaco": 10,
    "margem": 14,
}


def esquema_do_sistema() -> str:
    """Le a preferencia clara/escura do sistema operacional."""
    try:
        hints = QGuiApplication.styleHints()
        if hints.colorScheme() == Qt.ColorScheme.Dark:
            return ESCURO_
    except (AttributeError, RuntimeError):
        # colorScheme() so existe a partir do Qt 6.5; sem ele, claro e a aposta
        # mais segura porque nunca fica ilegivel.
        pass
    return CLARO_


def fichas(modo: str) -> dict[str, str]:
    if modo == AUTO:
        modo = esquema_do_sistema()
    return ESCURO if modo == ESCURO_ else CLARO


def folha_de_estilo(modo: str) -> str:
    c = fichas(modo)
    m = METRICA
    return f"""
/* ---------- base ---------- */
QWidget {{
    background: {c['fundo']};
    color: {c['texto']};
    font-size: 13px;
}}
QMainWindow, QDialog {{ background: {c['fundo']}; }}

/* ---------- cartoes do painel ---------- */
QFrame#cartao {{
    background: {c['superficie']};
    border: 1px solid {c['borda']};
    border-radius: {m['raio']}px;
}}
QLabel#tituloCartao {{
    color: {c['texto_suave']};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
}}
QLabel#rotuloCampo {{ color: {c['texto_suave']}; background: transparent; }}
QLabel#dica {{ color: {c['texto_suave']}; font-size: 11px; background: transparent; }}
QLabel {{ background: transparent; }}

/* ---------- cabecalho ---------- */
QFrame#cabecalho {{
    background: {c['superficie']};
    border-bottom: 1px solid {c['borda']};
}}
QLabel#marca {{ font-size: 15px; font-weight: 700; background: transparent; }}
/* Selo de alerta do cabecalho: precisa ser lido de relance, do outro lado da
   sala, enquanto a gravacao corre. Por isso fundo cheio em vez de so texto. */
QLabel#seloAviso {{
    background: {c['aviso']};
    color: #ffffff;
    border-radius: {m['raio_pequeno']}px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}

/* ---------- campos ---------- */
QComboBox, QSpinBox, QLineEdit {{
    background: {c['superficie_alta']};
    border: 1px solid {c['borda']};
    border-radius: {m['raio_pequeno']}px;
    padding: 5px 9px;
    min-height: {m['altura_controle'] - 12}px;
    selection-background-color: {c['destaque']};
}}
QComboBox:hover, QSpinBox:hover {{ border-color: {c['borda_forte']}; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {c['destaque']}; }}
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled {{
    color: {c['texto_suave']};
    background: {c['fundo']};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {c['texto_suave']};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {c['superficie']};
    border: 1px solid {c['borda']};
    border-radius: {m['raio_pequeno']}px;
    padding: 4px;
    outline: none;
    selection-background-color: {c['destaque_suave']};
    selection-color: {c['texto']};
}}

/* ---------- botoes ---------- */
QPushButton {{
    background: {c['superficie_alta']};
    border: 1px solid {c['borda']};
    border-radius: {m['raio_pequeno']}px;
    padding: 7px 14px;
    min-height: {m['altura_controle'] - 14}px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {c['superficie']}; border-color: {c['borda_forte']}; }}
QPushButton:pressed {{ background: {c['fundo']}; }}
QPushButton:disabled {{ color: {c['texto_suave']}; background: {c['fundo']}; }}

QPushButton#primario {{
    background: {c['destaque']};
    color: {c['destaque_texto']};
    border: 1px solid {c['destaque']};
}}
QPushButton#primario:hover {{ background: {c['destaque']}; border-color: {c['texto']}; }}
QPushButton#primario:disabled {{
    background: {c['fundo']};
    color: {c['texto_suave']};
    border-color: {c['borda']};
}}
QPushButton#gravando {{
    background: {c['perigo']};
    color: #ffffff;
    border: 1px solid {c['perigo']};
}}
QPushButton#discreto {{
    background: transparent;
    border: 1px solid transparent;
    color: {c['texto_suave']};
    padding: 5px 9px;
    font-weight: 500;
}}
QPushButton#discreto:hover {{ background: {c['superficie_alta']}; color: {c['texto']}; }}
QPushButton#discreto:checked {{
    background: {c['destaque_suave']};
    color: {c['destaque']};
}}

/* ---------- controles ---------- */
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {c['borda_forte']};
    border-radius: 4px;
    background: {c['superficie_alta']};
}}
QCheckBox::indicator:checked {{
    background: {c['destaque']};
    border-color: {c['destaque']};
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {c['borda']};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {c['destaque']}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {c['superficie']};
    border: 2px solid {c['destaque']};
    width: 12px; height: 12px;
    margin: -6px 0;
    border-radius: 8px;
}}

QProgressBar {{
    background: {c['superficie_alta']};
    border: 1px solid {c['borda']};
    border-radius: {m['raio_pequeno']}px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {c['destaque']}; border-radius: {m['raio_pequeno']}px; }}

/* ---------- barra de rolagem ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {c['borda_forte']};
    border-radius: 5px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['texto_suave']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- barra de status ---------- */
QStatusBar {{
    background: {c['superficie']};
    border-top: 1px solid {c['borda']};
    color: {c['texto_suave']};
}}
QStatusBar::item {{ border: none; }}

QToolTip {{
    background: {c['superficie_alta']};
    color: {c['texto']};
    border: 1px solid {c['borda_forte']};
    border-radius: {m['raio_pequeno']}px;
    padding: 5px 8px;
}}
"""


def aplicar(app, modo: str) -> None:
    app.setStyleSheet(folha_de_estilo(modo))
