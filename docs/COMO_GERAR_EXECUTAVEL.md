# Como gerar o executável

Empacota o programa numa pasta que roda **sem Python instalado**. O usuário final
copia a pasta e dá duplo clique.

Antes de empacotar, garanta que o programa roda do código-fonte:
[COMO_RODAR.md](COMO_RODAR.md). Empacotar não conserta nada — só congela o que já
existe.

---

## Resumo

```powershell
pip install pyinstaller
python -m PyInstaller --noconfirm --clean capturador.spec
```

O resultado sai em **`dist/Captura USB/`**. O executável é o
`Captura USB.exe` dentro dela.

---

## Passo a passo (Windows)

**1. Instale o PyInstaller** (uma vez):

```powershell
pip install pyinstaller
```

**2. Gere**, a partir da raiz do projeto:

```powershell
python -m PyInstaller --noconfirm --clean capturador.spec
```

Use `python -m PyInstaller` e não `pyinstaller` direto: o comando só funciona se
a pasta `Scripts` do Python estiver no `PATH`, o que frequentemente não está.
O `-m` sempre funciona.

| Opção | Para quê |
|---|---|
| `--noconfirm` | sobrescreve `dist/` sem perguntar |
| `--clean` | limpa o cache antes; use quando trocar de versão de dependência |

**3. Teste o que saiu** — sempre, e numa máquina sem Python quando possível:

```powershell
& '.\dist\Captura USB\Captura USB.exe'
```

Números medidos nesta máquina (Python 3.14.4, PyInstaller 6.20.0):

| | |
|---|---|
| Tempo de build | ~100 s |
| `dist/Captura USB/` | 227 MB, 327 arquivos |
| `Captura USB.exe` | 5 MB (o resto são as bibliotecas ao lado) |
| Memória com a janela aberta | ~92 MB |

**4. Distribua a pasta `dist/Captura USB/` inteira.** O `.exe` sozinho não roda:
as DLLs do Qt e do FFmpeg estão ao lado dele. Compacte a pasta em `.zip`.

---

## Linux

O mesmo comando, do mesmo diretório:

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --clean capturador.spec
```

Sai um binário `dist/Captura USB/Captura USB` (sem extensão) em vez do `.exe`.

**Não existe compilação cruzada.** O executável do Windows tem de ser gerado numa
máquina Windows, e o do Linux numa máquina Linux. O `.spec` funciona nos dois; só
a máquina de build muda.

---

## O que o usuário final ainda precisa instalar

**Nada, no Linux.**

**No Windows, o FFmpeg de linha de comando:**

```powershell
winget install Gyan.FFmpeg
```

Ele **não** é embutido de propósito: seriam ~80 MB adicionais para uma chamada
que só serve para enumerar os formatos que a placa aceita
([ADR-0002](adr/0002-ffmpeg-embutido-via-pyav.md),
[ADR-0018](adr/0018-empacotar-com-pyinstaller-em-modo-pasta.md)).

Vale incluir essa linha no `LEIA-ME.txt` ao lado do `.zip` que você entregar: sem
o FFmpeg o programa abre normalmente e **nenhuma placa aparece na lista** — o
sintoma não sugere a causa.

---

## Mexendo na receita

Tudo mora em [`capturador.spec`](../capturador.spec), que é um script Python
comum executado pelo PyInstaller.

### Acrescentar um ícone

Coloque um `.ico` (Windows) em `recursos/icone.ico` e mude, no bloco `EXE`:

```python
icon="recursos/icone.ico",
```

### Ver os erros de inicialização

Por padrão o executável roda **sem console** — é um aplicativo de janela. O
efeito colateral é que, se ele morrer antes de abrir a janela, nada aparece em
lugar nenhum. E `--listar` / `--medir` não imprimem no executável empacotado,
pelo mesmo motivo.

Para depurar, mude no bloco `EXE`:

```python
console=True,
```

Regenere, rode pelo terminal, leia o erro, e **desfaça a mudança** antes de
distribuir.

### Arquivo único (`--onefile`)

Se você preferir um `.exe` solto a uma pasta, junte `EXE` e `COLLECT` num bloco
só (troque `exclude_binaries=True` por `a.binaries, a.datas` no `EXE` e remova o
`COLLECT`).

Saiba o que está trocando: os 227 MB passam a ser **descompactados num diretório
temporário a cada abertura**. Em SSD são ~2 s de atraso antes da janela; em disco
mecânico, bem mais. O modo pasta foi escolhido por isso
([ADR-0018](adr/0018-empacotar-com-pyinstaller-em-modo-pasta.md)).

### Reduzir o tamanho

A lista `EXCLUIDOS` no `.spec` já tira os módulos Qt que o programa não usa
(WebEngine, Quick, Qml, Charts...). Dá para cortar mais, com cuidado: excluir um
módulo usado indiretamente produz um executável que abre e quebra ao clicar em
alguma coisa — sempre teste depois de mexer nessa lista.

Não use UPX. Ele reduziria o tamanho e quebra a assinatura das DLLs do Qt, além
de fazer o antivírus colocar o executável em quarentena.

---

## Quando o build falha

| Erro | Causa | Solução |
|---|---|---|
| `'pyinstaller' is not recognized` | `Scripts` fora do `PATH` | use `python -m PyInstaller` |
| `Spec file "capturador.spec" not found` | terminal em outra pasta | rode da **raiz** do projeto |
| Abre e morre no primeiro Iniciar | DLLs do PyAV não recolhidas | confirme `collect_dynamic_libs("av")` no `.spec` |
| `ModuleNotFoundError` ao abrir | módulo importado dinamicamente | acrescente-o a `hiddenimports` no `.spec` |
| `attempted relative import with no known parent package` | receita apontada para `capturador/__main__.py` | o ponto de entrada é `principal.py` — veja o comentário lá |

Diagnóstico geral: gere com `console=True`, rode pelo terminal e leia o traceback.
É a diferença entre depurar e adivinhar.

---

## Arquivos envolvidos

| Arquivo | Papel |
|---|---|
| [`capturador.spec`](../capturador.spec) | a receita: o que entra, o que fica de fora, como o executável é montado |
| [`principal.py`](../principal.py) | ponto de entrada do empacotamento — existe porque o PyInstaller não carrega `__main__.py` como parte do pacote |
| `build/` | trabalho intermediário do PyInstaller — descartável |
| `dist/` | o resultado — descartável, é regerado |

`build/` e `dist/` são artefatos e não pertencem ao controle de versão. Se o
projeto passar a usar Git, um `.gitignore` com `build/`, `dist/`, `__pycache__/`
e `*.pyc` é o mínimo.
