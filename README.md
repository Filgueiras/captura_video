# Captura USB

Visualizador e gravador para placas de captura USB (HDMI→USB, UVC/UAC).
Roda em **Windows** e **Linux** — testado em Windows 10 e em Zorin OS 18
(Ubuntu 24.04). Para a placa de captura os dois são equivalentes; o que difere
entre eles está lado a lado em [docs/COMO_RODAR.md](docs/COMO_RODAR.md).

Feito para resolver dois incômodos concretos: o OBS é complexo demais para "só
ver e gravar", e players genéricos negociam um formato ruim com a placa e
entregam imagem borrada.

| | |
|---|---|
| Instalar e abrir | [docs/COMO_RODAR.md](docs/COMO_RODAR.md) |
| Gerar o executável | [docs/COMO_GERAR_EXECUTAVEL.md](docs/COMO_GERAR_EXECUTAVEL.md) |
| Por que é assim | [docs/adr/](docs/adr/) — as decisões de arquitetura |
| A placa não aparece | [COMO_ENCONTRAR_A_PLACA.md](COMO_ENCONTRAR_A_PLACA.md) |

---

## O que ele faz

**Três tipos de fonte**

- **Placa de captura** (HDMI→USB)
- **Ecrã** — o desktop inteiro ou um monitor específico
- **Janela** — uma aplicação isolada, mesmo parcialmente coberta

No Windows a captura de ecrã usa a **Desktop Duplication API** (`ddagrab`), a
mesma via do OBS. Medido nesta máquina: **41 fps** contra 17 do método antigo
(`gdigrab`). Janelas específicas usam `gdigrab`, que é o único caminho para
alvos individuais — e entrega 30 fps sem esforço.

Capturar os dois monitores num arquivo só é possível, mas custa o dobro de
pixels: aqui o desktop combinado (3840x1080) caiu para 11 fps. Prefira um
monitor de cada vez.

**Encontra e configura sozinho**

- Lista as placas e **pareia vídeo com áudio do mesmo aparelho** — no Windows
  pelo `ContainerId`, no Linux pela topologia do sysfs. Sem isso é fácil gravar
  o microfone do PC sem perceber. Marque *Usar o áudio da própria placa* e ele
  cuida disso; desmarque para escolher outra fonte.
- **Grava o áudio do computador sem instalar nada.** Gravando ecrã ou janela, o
  som que se quer é o que sai pelas caixas, e ele aparece primeiro na lista como
  *Áudio do computador* — no Windows pelo WASAPI em modo loopback, no Linux pela
  fonte `.monitor` do PulseAudio/PipeWire. Nem driver, nem filtro DirectShow de
  terceiros, nem privilégio de administrador. Gravando uma placa, essa mesma
  fonte é a errada e vai para o fim da lista. Com ela selecionada, *Ouvir o
  áudio* fica travado: reproduzir o que acabou de ser capturado realimentaria a
  captura. Ver [ADR-0022](docs/adr/0022-audio-do-computador-por-wasapi.md).
- Escolhe o formato de maior qualidade real, preferindo codec comprimido.
  É a diferença entre 1080p e 640x480 na mesma placa.

**Mede em vez de confiar**

- **Testar equipamento** abre cada modo por alguns segundos e mede duas coisas:
  quantos quadros a placa entrega *de verdade* e quanto tempo *esta máquina*
  gasta processando cada um. Cada modo recebe um veredito — Fluido, No limite,
  Vai engasgar — e a lista fica colorida por ele.
- No fim, o app apresenta **as duas escolhas que fazem sentido**, porque não
  existe "a melhor": mais quadros por segundo e mais pixels por quadro competem
  pelo mesmo orçamento. Você decide pelo uso.
- **Gravar amostra** grava 10 segundos e depois *confere o arquivo*: quadros que
  sobreviveram, taxa efetiva, desencontro entre áudio e vídeo, e quantos MB por
  minuto aquilo consome.

**Grava**

- **Escolhe o destino a cada gravação.** Marcada a opção *Escolher ao gravar*,
  abre a caixa de salvar com um nome de data e hora já sugerido. Desmarcada,
  salva direto na pasta padrão sem perguntar.
- **Sem recomprimir** (perfil Original): os pacotes da placa vão para o arquivo
  sem serem decodificados. Qualidade idêntica à do hardware, CPU perto de zero,
  nenhuma perda de geração. Indisponível para ecrã e janela — a tela chega sem
  compressão, e "copiar" 1080p60 em BGRA seriam ~500 MB por segundo.
- **Em H.264** quando o objetivo é arquivo pequeno, com NVENC/QuickSync/AMF se a
  máquina tiver. Só aparecem os codificadores que **abrem de verdade** aqui —
  nada de escolher NVENC e descobrir na hora de gravar que o driver é velho.
- **Descarta os quadros de enchimento** que muitas placas emitem para fingir uma
  taxa que não sustentam. Sem esse filtro, metade dos quadros do arquivo fica
  corrompida numa cópia direta.
- **Avisa antes de gravar mudo.** Um selo no cabeçalho acusa, durante toda a
  captura, que não há som — porque nenhuma entrada foi escolhida, porque a
  entrada não abriu, porque ela abriu e nada chegou, ou porque **chega só
  silêncio**. Esse último caso é o que só contar blocos não pega: a fonte de
  áudio do computador entrega blocos sem parar mesmo com o PC mudo, e silêncio
  digital também é bloco. Por isso a verificação é feita nas amostras, e vale
  igual para placa e para tela. Ao clicar em Gravar, pergunta antes de começar,
  e a barra de status marca `sem áudio` (ou `silêncio`) ao lado do REC. Um
  arquivo mudo só costuma dar as caras quando já não dá para regravar.
  A opção *Avisar se faltar áudio* desliga a pergunta (o selo continua).

**Interface**

- Tema **claro, escuro ou automático** (segue o sistema).
- Prévia com proporção correta, tela cheia, foto em resolução nativa.
- Monitoração do áudio com volume e medidor de nível.

---

## Instalação

Versão curta; o passo a passo com diagnóstico e a **comparação do que cada
sistema precisa** estão em [docs/COMO_RODAR.md](docs/COMO_RODAR.md). Requer
Python 3.10 ou mais novo.

### Windows

```powershell
pip install -r requisitos.txt
winget install Gyan.FFmpeg
```

O FFmpeg de linha de comando é usado para enumerar os formatos que a placa
aceita — a captura em si não depende dele.

O `requisitos.txt` traz a `soundcard` no Windows: é por ela que se grava o som
que sai pelas caixas, via WASAPI em modo loopback, que o FFmpeg não alcança. Não
instala driver nem pede administrador ([ADR-0022](docs/adr/0022-audio-do-computador-por-wasapi.md)).

Se nenhuma placa aparecer: Configurações → Privacidade → Câmera → ative
**"Permitir que aplicativos da área de trabalho acessem sua câmera"**.

### Linux (Ubuntu, Zorin, Debian e derivados)

```bash
sudo apt install python3-venv v4l-utils
python3 -m venv ~/.venvs/captura_video
~/.venvs/captura_video/bin/pip install -r requisitos.txt
```

O **venv não é opcional**: no Ubuntu 24.04 e derivados (Zorin 18) o `pip` recusa
instalar no Python do sistema (PEP 668). O `capturar.sh` procura o ambiente
sozinho. Aqui não se instala o FFmpeg de linha de comando — quem enumera os
formatos no Linux é o `v4l-utils`; sem ele o app cai numa lista genérica.

Acesso a `/dev/video*` costuma já vir por ACL em sistemas com `systemd-logind`;
confira com `getfacl /dev/video0` e, se preciso, use
`sudo usermod -aG video $USER` (exige reentrar na sessão).

O áudio usa PulseAudio/PipeWire quando disponível e cai para ALSA caso
contrário — a escolha é automática e leva em conta o que o FFmpeg embutido no
PyAV realmente suporta. No caminho ALSA o app ainda repara a cópia do alsa-lib
que vem dentro do wheel do PyAV, que sobe sem configuração e faria a gravação
sair muda ([ADR-0020](docs/adr/0020-reparar-o-alsa-embutido-no-pyav.md)).

**Captura de ecrã e de janela exigem sessão Xorg** — sob Wayland gravam preto.
A placa de captura funciona nas duas sessões.

Em Fedora: `sudo dnf install v4l-utils`. Em Arch: `sudo pacman -S v4l-utils`.

---

## Uso

É um aplicativo de janela (desktop), não uma página no navegador.

**Windows** — duplo clique em `Captura USB.bat`.
**Linux** — `./capturar.sh` (uma vez: `chmod +x capturar.sh`).

Ou, de dentro da pasta do projeto:

```bash
python -m capturador             # abre a janela
python -m capturador --listar    # dispositivos e formatos, sem abrir a janela
python -m capturador --medir     # mede a taxa real de cada modo no terminal
```

1. **Fonte** — escolha o tipo (placa, ecrã ou janela) e depois a fonte. Sendo
   placa, o áudio dela vem junto.
2. **Testar equipamento** (opcional, mas recomendado na primeira vez) — descobre
   o que a placa e a máquina realmente aguentam.
3. **Iniciar**.
4. **Gravar amostra** para conferir antes de valer, ou **Gravar** direto.

| Atalho | Ação |
|---|---|
| `Ctrl+R` | inicia/para a gravação |
| `Ctrl+T` | testar equipamento |
| `F11` / duplo clique | tela cheia |
| `F12` | foto em resolução nativa |
| `Esc` | sai da tela cheia |

---

## Perfis de gravação

| | Original | H.264 |
|---|---|---|
| Arquivo | `.mkv` | `.mp4` |
| Vídeo | cópia direta da placa | recodificado |
| Qualidade | idêntica ao hardware | ajustável |
| CPU/GPU | quase nada | moderado |
| Tamanho | ~150 MB/min a 1080p30 | bem menor |
| Quando usar | arquivar, editar depois | compartilhar, guardar muito |

O **fator de qualidade** vale só para H.264: é o CRF (libx264) ou CQ (GPU).
Menor = melhor imagem e arquivo maior. 18 é praticamente transparente, 23 é o
padrão do x264, acima de 28 começa a aparecer.

MKV foi escolhido no perfil Original porque suporta MJPEG com áudio PCM e
sobrevive a um desligamento no meio da gravação — o arquivo continua abrindo.

---

## Estrutura

| Arquivo | Papel |
|---|---|
| [capturador/dispositivos.py](capturador/dispositivos.py) | enumeração e pareamento por plataforma; único lugar com código específico de SO |
| [capturador/captura.py](capturador/captura.py) | leitura das threads, remultiplexação, codificação, medição |
| [capturador/tema.py](capturador/tema.py) | fichas de design e folha de estilo |
| [capturador/janela.py](capturador/janela.py) | interface |
| [capturador/__main__.py](capturador/__main__.py) | linha de comando |
| [capturador.spec](capturador.spec) | receita do PyInstaller |
| [principal.py](principal.py) | ponto de entrada do executável empacotado |

### Mexendo no layout

Duas alavancas, de propósito:

- **Cores e medidas** — só existem em [tema.py](capturador/tema.py), nos
  dicionários `CLARO`, `ESCURO` e `METRICA`. Mudar a cor de destaque do app
  inteiro é editar uma linha. Nenhum valor de cor aparece solto no resto do
  código.
- **Ordem dos cartões** — a lista `_CARTOES` no topo de `JanelaPrincipal`. Cada
  item é `(título, nome do método que devolve o conteúdo)`. Reordenar a lista
  reordena o painel; remover um item remove o cartão.

### Notas de arquitetura

Vídeo e áudio são abertos como containers separados, cada um na sua thread — no
Linux nem existe a opção de juntá-los numa entrada só. A sincronia vem de uma
âncora de relógio comum tomada no instante em que a gravação começa, o que
preserva os tempos suaves gerados pela placa e ainda assim alinha o início dos
dois fluxos. Medido: ~2 ms de deriva por hora.

Trabalho demorado (enumerar, parear, testar) roda em `QThread` e volta por
sinal. O pareamento no Windows leva alguns segundos, então a lista de
dispositivos aparece primeiro e a associação de áudio chega depois — sem
sobrescrever uma escolha que você já tenha feito.

Essas e as outras decisões estão registradas uma a uma, com o problema que
resolvem e as alternativas descartadas, em [docs/adr/](docs/adr/). Vale a
consulta antes de "simplificar" alguma coisa que pareça estranha — várias
linhas do código parecem redundantes e não são.

---

## Problemas comuns

**"Não foi possível abrir" / "dispositivo em uso"** — a placa aceita um programa
por vez. Feche VLC, OBS, abas de navegador com câmera, Discord, Teams.

**Taxa de quadros abaixo do esperado** — pode ser a placa anunciando mais do que
entrega. Rode *Testar equipamento*: ele mostra a taxa real de cada modo.

**Tela preta** — sem sinal na entrada HDMI, ou conteúdo com HDCP (Netflix,
Blu-ray, console em certos modos), que não é capturável por hardware nenhum.

Diagnóstico detalhado, com comandos para os dois sistemas, em
[COMO_ENCONTRAR_A_PLACA.md](COMO_ENCONTRAR_A_PLACA.md).
