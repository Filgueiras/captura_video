# ADR-0016 — Aparência centralizada em `tema.py`, painel montado por lista

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Interfaces em Qt apodrecem de um jeito previsível: cores em hexadecimal
espalhadas por `setStyleSheet` local, margens digitadas em cada layout, e a
ordem dos elementos enterrada em quinze chamadas de `addWidget` no meio de 300
linhas de construção. Mudar a cor de destaque vira uma caçada, e mover um bloco
de lugar vira uma cirurgia.

Além disso, o programa precisa de tema claro **e** escuro — um visualizador de
vídeo é usado tanto em sala clara quanto no escuro.

## Decisão

**Duas alavancas, de propósito.**

**1. Cores e medidas só existem em [`tema.py`](../../capturador/tema.py)**, nos
dicionários `CLARO`, `ESCURO` e `METRICA`. A folha de estilo inteira é gerada a
partir deles. Nenhum valor de cor aparece solto no resto do código; os widgets
pintados à mão (`MedidorAudio`) recebem as fichas por parâmetro.

Trocar a cor de destaque do aplicativo inteiro é editar uma linha.

Exceção deliberada: `LONA_VIDEO` (o fundo da área de vídeo) é escuro nos **dois**
temas. É o fundo neutro contra o qual a imagem capturada é julgada, e alterná-lo
mudaria a percepção das cores do que se está capturando.

**2. O painel lateral é montado a partir de uma lista.** No topo de
`JanelaPrincipal`:

```python
_CARTOES = [
    ("Fonte",       "_cartao_fonte"),
    ("Gravação",    "_cartao_gravacao"),
    ("Monitoração", "_cartao_audio"),
]
```

Cada item é `(título, nome do método que devolve o conteúdo)`. Reordenar a lista
reordena a interface; remover um item remove o cartão. Nenhuma outra linha
precisa mudar.

O tema tem três modos: **Auto** (segue o sistema, via `styleHints().colorScheme()`),
**Claro** e **Escuro**.

## Consequências

- Ajustar aparência é trabalho de minutos e não corre risco de deixar um canto
  com a cor antiga.
- A ordem da interface fica declarada num lugar visível, em vez de emergir da
  ordem das chamadas.
- Os dois temas ficam consistentes por construção: todo widget lê das mesmas
  chaves.
- `colorScheme()` só existe a partir do Qt 6.5. Sem ele, o modo Auto cai para
  **claro** — a aposta que nunca fica ilegível, porque texto escuro sobre fundo
  claro é o padrão de qualquer estilo do Qt.
- Trocar `objectName` em tempo de execução (o botão Gravar vira `#gravando`)
  exige `unpolish`/`polish` para o seletor pegar. É uma peculiaridade do Qt, não
  do desenho — está comentada no ponto de uso.
- Um cartão precisa ser um método sem argumentos que devolve um `QWidget`. É uma
  convenção não verificada: quebrá-la só aparece em tempo de execução.
- Folha de estilo em string é menos verificável que código: um seletor com erro
  de digitação falha em silêncio.

**Restrições de largura que parecem arbitrárias e não são.** O painel tem largura
fixa (360 px), e três detalhes existem só para ele não estourar em telas com
escala 125% ou fonte grande:

- `QCheckBox` não elide nem quebra o próprio rótulo — a largura mínima dele é o
  texto inteiro. Por isso os rótulos de caixa de seleção são curtos ("Áudio da
  placa") e a explicação vai numa `QLabel` separada, que quebra linha.
- `QComboBox` exige, por padrão, a largura do item mais longo. Nomes de
  dispositivo são compridos. `_combo()` cria uma caixa que aceita ser mais
  estreita que o conteúdo e elide o texto; a lista suspensa continua mostrando o
  nome inteiro.
- Caminhos de pasta não têm espaços, então `wordWrap` não ajuda — o `QLabel`
  passa a exigir a largura da maior "palavra". `RotuloElidido` corta no meio,
  preservando início e fim, que é o que identifica um caminho.

## Alternativas consideradas

**Arquivo `.qss` externo.** Permitiria trocar o tema sem tocar no código, e
perderia a interpolação (`{c['destaque']}`) que garante que os dois temas usem
exatamente as mesmas chaves — além de virar mais um arquivo para empacotar.

**Qt Designer / arquivos `.ui`.** Layout visual, ao custo de código gerado e de
uma ordem de elementos que só se lê abrindo a ferramenta.

**Só seguir o tema do sistema, sem escolha manual.** Menos controles, e ignora
que a preferência para um aplicativo de vídeo pode ser diferente da do resto do
sistema.
