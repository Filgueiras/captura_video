# ADR-0003 — Todo código específico de sistema operacional em `dispositivos.py`

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Windows e Linux não se parecem em nada na hora de descobrir e abrir uma placa de
captura:

| | Windows | Linux |
|---|---|---|
| Demuxer de vídeo | `dshow` | `v4l2` |
| Demuxer de áudio | `dshow` | `pulse` ou `alsa` |
| Enumerar | `ffmpeg -list_devices` | varrer `/dev/video*` |
| Formatos aceitos | `ffmpeg -list_options` | `v4l2-ctl --list-formats-ext` |
| Nome do dispositivo | `video=Nome Amigável` | `/dev/video0` |
| Fixar o formato | `vcodec=` ou `pixel_format=` | `input_format=` |
| Parear com o áudio | `ContainerId` (PowerShell) | topologia do sysfs |
| Capturar o ecrã | `ddagrab` / `gdigrab` | `x11grab` |

Espalhar `if WINDOWS:` por três módulos produziria a bagunça clássica: a
interface sabendo o que é um `/dev/video0`, o motor de captura sabendo o que é um
`ContainerId`, e cada correção de bug precisando ser feita duas vezes.

## Decisão

**Um único módulo** — [`dispositivos.py`](../../capturador/dispositivos.py) —
conhece o sistema operacional. Ele exporta apenas dataclasses neutras
(`DispositivoVideo`, `DispositivoAudio`, `ModoVideo`, `Dispositivos`) e funções
que devolvem essas dataclasses.

A peça central é o método `DispositivoVideo.entrada(modo, cursor)`, que devolve
a tripla `(caminho, formato, opções)` pronta para o `av.open()`. **Quem sabe
como uma fonte quer ser aberta é a própria fonte.** O motor de captura chama
`entrada()` e não faz ideia se está falando com uma placa USB, com a Desktop
Duplication API ou com o `x11grab`.

## Consequências

- [`captura.py`](../../capturador/captura.py) e
  [`janela.py`](../../capturador/janela.py) não têm um único `platform.system()`.
- Acrescentar um tipo de fonte novo (uma câmera de rede, por exemplo) é
  acrescentar um ramo em `entrada()` e uma função de enumeração — nada muda no
  motor nem na interface. Foi assim que ecrã e janela entraram depois da placa.
- Suportar um sistema novo (macOS, via `avfoundation`) fica confinado a um
  arquivo.
- O módulo é grande (~830 linhas) e é o único do projeto que não cabe na cabeça
  de uma vez. É o preço: a complexidade não desaparece, ela fica **num lugar
  só**, onde é visível, em vez de distribuída onde não é.
- `dispositivos.py` importa `av` **dentro das funções**, não no topo. Assim ele
  continua utilizável (e testável) sem o PyAV instalado.

## Alternativas consideradas

**Uma classe abstrata `Plataforma` com subclasses `PlataformaWindows` e
`PlataformaLinux`.** Mais "correto" segundo o manual de orientação a objetos, e
pior na prática: as duas implementações compartilham quase toda a lógica de
ordenação, deduplicação e escolha de modo, que teria de subir para a classe base
ou ser duplicada. Com duas plataformas, dois `if` bem colocados custam menos que
uma hierarquia.

**Uma biblioteca de terceiros que abstraia dispositivos de captura.** Nenhuma
cobre os dois sistemas *e* expõe a lista de formatos por dispositivo — que é o
dado do qual todo o resto depende.
