# ADR-0024 — Janela pelo `window_id`, e Wayland detectado pelo tipo de sessão

**Estado:** Aceito
**Data:** 2026-09-18

Refina o [0012](0012-ecra-por-ddagrab-janela-por-gdigrab.md) no lado Linux.

## Contexto

Três defeitos separados, todos na captura de ecrã e de janela no Linux, todos
visíveis numa instalação limpa de Zorin 18 / Ubuntu 24.04.

**1. A detecção de Wayland testava a variável errada.** A condição era
`WAYLAND_DISPLAY and not DISPLAY`. O XWayland mantém `DISPLAY` definida, e sessão
Wayland *com* XWayland é a configuração **padrão** do GNOME nessas distribuições.
Ou seja: a guarda nunca disparava justamente onde precisava. Medido nesta
máquina, o `x11grab` sobre a raiz abre sem erro, informa `1280x720` corretamente
e entrega quadros com **todo pixel em zero**. O programa oferecia a opção com
confiança e o usuário só descobria o problema depois de gravar.

**2. Capturar "uma janela" era capturar um retângulo da tela.** A entrada era
`DISPLAY+x,y` com o tamanho fixado, tudo lido no momento em que a lista foi
montada. Mover a janela durante a gravação deixava o arquivo mostrando o que
passou a ocupar aquele lugar; redimensioná-la, idem.

**3. A enumeração dependia de `wmctrl` e `xdotool`, que ninguém tem.** Nenhum
dos dois vem instalado em Ubuntu/Zorin. Sem eles `listar_janelas()` devolvia
lista vazia, e a interface dizia *"Nenhuma janela encontrada"* — acusando o
sistema errado, já que havia janelas de sobra.

## Decisão

**Capturar a janela pelo `window_id` do x11grab**, em vez de um retângulo de
coordenadas. É opção nativa do demuxer (`-window_id`), e o identificador em hexa
já vinha da enumeração.

**Detectar Wayland por `XDG_SESSION_TYPE`**, que vem do logind, com
`WAYLAND_DISPLAY` como reforço para quem roda fora de uma sessão do logind.

**Enumerar janelas com `xprop` + `xwininfo`**, do pacote `x11-utils`, que
acompanha qualquer instalação gráfica dessas distribuições. `xprop -root
_NET_CLIENT_LIST` dá as janelas que o gerenciador gerencia — a mesma propriedade
que o `wmctrl` lia — e `xwininfo -id` dá título, geometria e estado de mapeamento.

E, o ponto que só apareceu ao medir: **ecrã e janela não têm o mesmo destino sob
Wayland.**

| | Sessão Xorg | Sessão Wayland |
|---|---|---|
| Ecrã | funciona | **não é oferecido** — o `x11grab` sobre a raiz grava preto |
| Janela | funciona | **funciona**, para clientes XWayland |

Capturar uma janela pelo `window_id` funciona numa sessão Wayland, porque a
janela do XWayland é uma janela X de verdade. Medido: uma janela pintada de
`rgb(200, 30, 30)` foi capturada com o pixel central exatamente em
`[200 30 30]`, enquanto a mesma sessão devolvia preto na captura da raiz. E a
seleção sai de graça: `_NET_CLIENT_LIST` só lista clientes X, então aplicativos
Wayland nativos — que realmente não dá para capturar por aqui — nem chegam a
aparecer na lista.

Por isso `motivo_sem_ecra()` e `_impedimento_janela()` são funções diferentes,
em vez de uma só: sob Wayland a primeira bloqueia e a segunda não.

## Consequências

- **Sob Wayland deixa de existir a gravação preta silenciosa.** A opção de ecrã
  some da lista e a interface explica por quê, com o caminho para uma sessão
  Xorg, em vez de deixar a lista vazia sem justificativa.
- **Ganha-se captura de janela sob Wayland**, que antes era bloqueada junto com
  a de ecrã pela mesma guarda. É parcial — só XWayland —, mas parcial e honesta,
  porque a lista mostra exatamente o conjunto que funciona.
- **Some uma dependência em vez de aparecer outra.** `wmctrl` e `xdotool` saem;
  `x11-utils` entra e já está instalado. E uma chamada de subprocesso a menos por
  janela enumerada, já que o `xwininfo` dá título e geometria de uma vez.
- Janelas minimizadas ficam de fora, por `Map State: IsViewable`. Capturar uma
  devolveria o que tivesse sobrado no buffer.
- **A captura ainda é do conteúdo que o X tem**, não uma composição privada: numa
  sessão Xorg sem compositor, uma janela coberta por outra grava o que está por
  cima. É o mesmo comportamento de antes; o `window_id` corrige o
  acompanhamento de posição e tamanho, não a oclusão.
- Passa a haver duas mensagens de diagnóstico a manter em dia. Elas moram em
  `dispositivos.py` junto do teste que as produz, e não na interface, para não
  repetir a regra em dois lugares
  ([0003](0003-fronteira-de-plataforma-em-dispositivos.md)).

## Alternativas consideradas

**`xdg-desktop-portal` + PipeWire.** Continua sendo a resposta certa para
capturar o ecrã sob Wayland, e continua fora — é um protocolo inteiro, com
diálogo de permissão do sistema e negociação de fluxo, para um recurso
secundário deste programa. O que mudou é que agora o programa diz isso ao
usuário em vez de gravar preto.

**Manter `wmctrl`/`xdotool` e só documentar melhor o `apt install`.** Mais
simples de escrever. Rejeitado porque transfere para o usuário um passo que o
programa consegue evitar: o `x11-utils` já está lá em toda máquina onde este
programa abre.

**Ler o X diretamente pelo Qt, sem subprocesso.** O PySide6 já está carregado e
saberia listar as janelas. Rejeitado por
[0003](0003-fronteira-de-plataforma-em-dispositivos.md): `dispositivos.py` não
importa Qt, e é ele que serve o `--listar`, que roda sem interface.
