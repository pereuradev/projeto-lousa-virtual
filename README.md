# Projeto Lousa Virtual

Lousa virtual para Windows feita em Python, com OpenCV, MediaPipe e uma webcam. Permite desenhar com uma pinça entre polegar e indicador, escolher cores por gestos e salvar o resultado em PNG. Também funciona com o mouse.

## Como funciona

- **Desenhar:** mova o indicador para posicionar o cursor; una polegar e indicador para riscar e separe para parar.
- **Ativar as cores:** mantenha apenas o polegar estendido, fazendo um joinha, por **1 segundo**. Solte o joinha antes de escolher.
- **Escolher uma cor:** no modo Cores, mostre a mesma quantidade de dedos de **uma mão** durante **5 segundos**. Depois da escolha, o aplicativo volta ao desenho.
- **Limpar:** mantenha **as duas mãos abertas por 2 segundos**. Fechar ou retirar uma delas antes de completar cancela. Desfazer recupera o desenho.

| Dedos no modo Cores | Cor |
|---|---|
| 1 | Preto |
| 2 | Azul |
| 3 | Vermelho |
| 4 | Verde |
| 5 | Roxo |

A contagem de cores fica desligada no modo Desenho para não interferir na preparação da pinça. A interface mostra o modo ativo e o progresso dos gestos. Uma mão aberta não limpa a lousa.

Outros recursos: cinco cores clicáveis, caneta, borracha, espessura ajustável, suavização do cursor, câmera espelhada, seleção de câmera, pausa dos gestos, histórico de até 25 ações e exportação do desenho em **1280 × 800 pixels**.

## Instalação no Windows

Requisitos: **Windows x64**, conexão à internet na primeira instalação e [uv](https://docs.astral.sh/uv/getting-started/installation/) instalado. A webcam é necessária para os gestos; o mouse funciona sem câmera.

1. Baixe o ZIP deste repositório e extraia os arquivos, ou clone com Git:

   ```powershell
   git clone https://github.com/pereuradev/projeto-lousa-virtual.git
   cd projeto-lousa-virtual
   ```

2. Execute **Instalar ou reparar.cmd** dentro da pasta do projeto.
3. Aguarde o download do Python, das dependências e do modelo oficial de rastreamento de mãos.
4. Abra **Iniciar Lousa.cmd**.

O instalador cria o Python em `.python` e o ambiente em `.venv`, sem exigir uma instalação global de Python. As dependências ficam fixadas em `requirements.lock.txt`. O modelo não é versionado: o instalador baixa a versão oficial e confere seu SHA256.

Se houver erro ao abrir a câmera, feche aplicativos que a estejam usando, confira a conexão e a permissão de câmera para aplicativos da área de trabalho. É possível escolher outro número de câmera na lateral ou continuar com o mouse.

## Uso e atalhos

Os desenhos são salvos na pasta `desenhos/`, com nomes únicos. O PNG contém apenas a lousa, sem câmera, cursor ou controles.

| Ação | Atalho |
|---|---|
| Cores | 1–5 |
| Alternar borracha | E |
| Voltar à caneta | B |
| Ajustar espessura | + / − |
| Desfazer | Z ou Ctrl+Z |
| Limpar com confirmação | C |
| Salvar PNG | S |
| Pausar gestos | Espaço |
| Ajuda | F1 |
| Fechar | Esc |

Para abrir sem ativar a webcam:

```powershell
& '.\Iniciar Lousa.cmd' --no-camera
```

Instruções completas de gestos, cancelamentos e uso da câmera: [LEIA-ME.md](LEIA-ME.md).

## Desenvolvimento e testes

Ambiente validado: Python **3.12.13**, OpenCV contrib **4.14.0.94**, MediaPipe **1.1.1** e Pillow **12.2.0**.

Depois da instalação, na raiz do projeto:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
& '.\.venv\Scripts\python.exe' main.py --camera 0
```

O projeto possui **81 testes automatizados**, cobrindo desenho, PNG, histórico, contagem de dedos, ativação por joinha, temporização, cancelamentos e comunicação entre a câmera e a interface. Os testes não abrem a webcam.

O diagnóstico abaixo abre a câmera brevemente e retorna somente contagens e erros, sem salvar frames:

```powershell
& '.\.venv\Scripts\python.exe' main.py --diagnose
```

O joinha e suas transições foram testados com landmarks e tempo simulados; ainda precisam de validação de uso com uma pessoa diante da câmera. Iluminação, enquadramento e oclusões podem afetar o reconhecimento. Mais detalhes em [VALIDACAO.md](VALIDACAO.md).

## Estrutura

```text
main.py                  Entrada do aplicativo
lousa/app.py             Interface Tkinter e controles
lousa/camera.py          Captura e rastreamento de até duas mãos
lousa/controls.py        Modos, gestos e temporizadores
lousa/drawing.py         Desenho, histórico e exportação
tests/                   Testes sem webcam
models/                  Modelo obtido pelo instalador
setup.ps1                Instalação e reparo do ambiente
requirements.lock.txt    Dependências fixadas
```

## Privacidade

O aplicativo processa imagens na memória do computador, não faz upload de imagens, não grava vídeo e não usa microfone. Somente o desenho é exportado quando solicitado.

A documentação do MediaPipe informa processamento local das imagens e coleta de métricas de desempenho/utilização pela biblioteca; não se promete ausência absoluta de comunicação de rede. Consulte o [aviso oficial do MediaPipe](https://pypi.org/project/mediapipe/).

Ambientes Python, caches, logs, arquivos de configuração sensíveis e desenhos pessoais ficam fora do versionamento.
