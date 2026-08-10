# ADR-0014 — Trabalho demorado em `QThread`: listar primeiro, parear depois

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Três operações do programa são lentas o bastante para congelar a janela se
rodarem na thread da interface:

| Operação | Custo | Por quê |
|---|---|---|
| Enumerar dispositivos | ~1 s | cada sondagem do `dshow` espera 1–2 s pela resposta |
| Parear vídeo↔áudio (Windows) | vários segundos | consulta ao PowerShell ([0011](0011-parear-video-e-audio-pelo-aparelho.md)) |
| Testar equipamento | 30 s ou mais | abre cada modo por segundos ([0009](0009-medir-em-vez-de-confiar.md)) |

Uma janela congelada é indistinguível de um programa travado, e o Windows chega
a pintá-la de branco com "Não está respondendo".

## Decisão

Cada uma roda em `QThread` e devolve o resultado por **sinal**
(`TrabalhoEnumeracao` e `TrabalhoTeste` em
[`janela.py`](../../capturador/janela.py)). Sinais do Qt atravessam threads com
segurança, o que dispensa lock na ponta da interface.

A parte que importa é `TrabalhoEnumeracao` emitir **dois** sinais:

```python
resultado = disp.listar()
self.listou.emit(resultado)     # lista completa, ~1 s — aparece já
if disp.parear(resultado):
    self.pareou.emit(resultado) # pareamento, vários segundos — chega depois
```

A lista aparece assim que existe; o pareamento a enriquece quando fica pronto. E
há uma regra explícita para a chegada tardia: **se o usuário já mexeu no combo de
áudio, o pareamento não sobrescreve a escolha dele** — é o que a flag
`_audio_tocado_pelo_usuario` guarda.

Enquanto a captura está rodando, os controles que exigiriam reabrir o dispositivo
ficam **travados** (`_travar()`). Trocar de placa ou de formato com a prévia no ar
produziria um estado em que a tela mostra uma coisa e a gravação usa outra.

## Consequências

- A janela nunca congela, nem na inicialização, nem no teste de 30 segundos.
- A lista de dispositivos aparece em ~1 s em vez de esperar o pareamento.
- Uma escolha manual do usuário nunca é desfeita por um resultado que chegou
  depois — o tipo de bug que faz o programa parecer possuído.
- O teste de equipamento reporta progresso (`progresso.emit(indice, total, rótulo)`)
  e pode ser cancelado, o que o `closeEvent` usa para não travar o fechamento.
- Só **um** trabalho de fundo por vez: `_trabalho` guarda a referência e as ações
  verificam `isRunning()` antes de começar. Duas enumerações simultâneas
  disputariam o mesmo dispositivo.
- Manter a referência é obrigatório: um `QThread` sem referência viva é coletado
  pelo Python no meio da execução e derruba o processo.
- Estado assíncrono é mais difícil de raciocinar que código sequencial. É o custo
  de uma interface que responde.

## Alternativas consideradas

**`QApplication.processEvents()` dentro dos laços lentos.** O truque clássico.
Mantém a janela pintando e permite reentrância — o usuário clica em "Testar" no
meio do teste e o programa reentra na própria função. Fonte inesgotável de bugs.

**`asyncio` com um laço de eventos integrado ao Qt.** Traz uma segunda máquina de
concorrência para um programa que já tem threads de captura
([0004](0004-video-e-audio-em-containers-separados.md)), para resolver um
problema que três `QThread` resolvem.

**Enumerar e parear num sinal só.** Simplifica o código e faz a lista demorar
vários segundos para aparecer — para exibir exatamente os mesmos dispositivos,
só que com o áudio já preenchido.
