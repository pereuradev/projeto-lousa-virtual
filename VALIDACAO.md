# Validação — cores ativadas por joinha

Atualização do Projeto Lousa Virtual em 26/10/2026.

## Comportamento entregue

- O aplicativo inicia em modo Desenho. Mostrar 1–5 dedos não seleciona cores nem bloqueia a preparação da pinça.
- Um joinha (somente o polegar estendido e os outros quatro dedos dobrados) por 1 segundo contínuo ativa o modo Cores.
- É necessário soltar o joinha antes de iniciar a contagem. Segurar a ativação não escolhe Preto.
- No modo Cores, exatamente uma mão com a mesma contagem por 5 segundos seleciona 1 Preto, 2 Azul, 3 Vermelho, 4 Verde ou 5 Roxo.
- Escolher a cor retorna automaticamente ao desenho. Outra troca por câmera exige novo joinha.
- Pinça cancela a escolha e libera desenho; perda de mão, pausa, interrupção de rastreamento e duas mãos também cancelam o modo Cores.
- Duas palmas abertas mantêm a limpeza por 2 segundos, com cancelamento, Desfazer, soltura obrigatória e intervalo de segurança de 3 segundos.
- A interface indica Desenho, Ativando cores e Cores ativadas, além do progresso. A paleta clicável, os atalhos e os demais recursos continuam disponíveis.

## Verificações

**81 testes passaram**, incluindo 32 testes específicos de controles. Foram verificados: desenho padrão sem contagem, joinha por exatamente 1 s, soltura antes da contagem, cinco cores após 5 s, retorno automático, cancelamento por pinça/perda/pausa, trava contra reativar segurando joinha (inclusive após escolher Preto), espelhamento e geometria sintéticos, duas mãos, limpeza com Desfazer, filas e separação de traços.

A interface foi verificada com widgets reais nos tamanhos 1000 × 640, 1180 × 780 e 1920 × 1080: botões e lateral couberam. Foram verificados os rótulos dos modos, progresso, caneta, borracha, cinco cores e Ajuda suspendendo os gestos. A revisão final do fluxo não deixou achados pendentes.

A validação foi realizada em um ambiente local Windows com as dependências fixadas neste repositório. Não houve gravação ou exportação de imagens da câmera.

## Limitação

O joinha e as transições foram testados com landmarks e tempo simulados. Ainda é necessário conferir o novo gesto com uma pessoa diante da webcam; não se declara validação real dessa execução. Iluminação, mão inteira visível e dedos bem definidos influenciam o rastreamento.
