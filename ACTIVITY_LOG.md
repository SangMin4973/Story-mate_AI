# Activity Log

이 파일은 프로젝트 진행 중 수행한 활동, 결정, 결과, 다음 작업을 계속 기록하기 위한 문서입니다.

## 2026-09-03

### 검색기 평가 방향 정리

- 챗봇 전체 평가 전에 검색기 성능을 먼저 평가하기로 결정했다.
- 검색기를 사용했을 때와 사용하지 않았을 때의 답변 품질을 이후 비교하기로 했다.
- 평가 데이터와 평가 결과 데이터를 분리해서 관리하기로 했다.
- 평가 스크립트는 `storymate/평가자료/scripts/` 안에서 관리하기로 했다.

### 평가자료 구조 정리

- 평가 데이터 디렉토리: `storymate/평가자료/data/`
- 평가 결과 디렉토리: `storymate/평가자료/results/`
- 평가 스크립트 디렉토리: `storymate/평가자료/scripts/`

### 검색기 평가 준비

- `storymate/평가자료/scripts/evaluate_retriever.py`를 생성했다.
- `storymate/평가자료/scripts/prepare_retriever_dataset.py`를 생성했다.
- 원본 검색기 평가셋 `김첨지_검색기_평가셋_v1.xlsx`를 읽어 정규화 데이터로 변환할 수 있게 했다.
- 검색 결과에서 동일 청크가 중복 집계되지 않도록 수정했다.

### 검색기 평가 결과 해석

- doc4 제외 결과:
  - `Recall@5`: `0.5167`
  - `MRR@5`: `0.3658`
  - `nDCG@5`: `0.3866`
- doc4 포함 결과:
  - `Recall@5`: `0.575`
  - `MRR@5`: `0.3506`
  - `nDCG@5`: `0.3744`
- doc4를 포함하면 말투 예시(`voice_example`) 검색은 크게 좋아졌다.
- 반면 사실, 심리, 성격 일반화 검색에서는 doc4가 핵심 근거를 뒤로 밀어내는 경향이 있었다.
- 결론적으로 doc4는 일반 검색기에 항상 포함하기보다 말투 참고용 검색기로 분리하는 방향이 적절하다고 판단했다.

### 다음 작업 후보

- Chroma DB에 `chunk_id`, `doc_id` metadata를 포함해 재생성하기
- chunk size와 overlap 조정하기
- doc1/doc2/doc3 기본 검색기와 doc4 말투 검색기를 분리하기
- BM25 + Vector hybrid 검색 도입 검토하기
- 검색기 사용 답변과 검색기 미사용 답변의 생성 평가 비교 준비하기

### 현재 RAG 로직의 문제점 메모

- 검색 결과에 `chunk_id`, `doc_id` metadata가 없어 평가셋의 정답 청크와 안정적으로 매칭하기 어렵다.
- Chroma DB가 문서별로 분리되어 있고, 검색 결과를 단순 점수 기준으로 합치기 때문에 문서 권위가 반영되지 않는다.
- `doc1`은 작품 사실의 최우선 근거인데, 현재 검색 로직에서는 `doc2`, `doc3`, `doc4`와 사실상 같은 수준으로 취급될 수 있다.
- `doc4`는 말투 참고용인데 일반 검색에 포함하면 사실/심리 근거를 밀어내는 노이즈가 된다.
- 벡터 검색만 사용하고 있어 금액, 장소, 이름, 사건 순서처럼 정확 키워드가 중요한 질문에서 약할 수 있다.
- chunk size가 작고 overlap이 거의 없어 한 질문에 필요한 맥락이 여러 청크로 쪼개질 가능성이 있다.
- 다중 근거 질문에서 필요한 청크를 모두 가져오는 능력이 낮다.
- 검색기가 질문 유형을 구분하지 않아서 사실 질문, 심리 질문, 말투 질문, 답변 불가 질문을 같은 방식으로 처리한다.
- 검색 결과의 relevance score만으로 정렬해서, 질문 의도에 맞는 doc 가중치나 rerank 단계가 없다.
- 검색 결과가 약하거나 무관해도 생성 단계에서 “모름”으로 답하게 하는 명확한 근거 부족 처리 로직이 약하다.
- 프롬프트에서 Doc1~Doc4의 역할과 권위 차이가 충분히 강하게 분리되어 있지 않다.
- RAG를 쓰지 않는 baseline과 RAG 사용 결과를 아직 같은 평가셋으로 비교하지 않았다.

### Chroma 데이터 수정 준비

- 기존 Chroma DB를 바로 덮어쓰기보다, 먼저 `embedding_metadata` 복사본을 만들어 평가하기로 했다.
- 평가셋 Corpus의 `chunk_id`, `doc_id`, `source_file`, `authority`, `chunk_type`, `source_lines`를 Chroma metadata로 저장하는 재생성 스크립트를 추가했다.
- 추가 스크립트: `storymate/평가자료/scripts/rebuild_chroma_with_metadata.py`
- 검색기 평가 스크립트에 `--embedding-dir-name` 옵션을 추가해서 `data/embedding`과 `data/embedding_metadata`를 교체 없이 비교할 수 있게 했다.
- 이 단계의 목적은 검색 결과와 평가셋 정답 청크를 문자열 유사도가 아니라 metadata 기준으로 안정적으로 매칭하는 것이다.

### Chroma metadata 재생성 결과 비교

- 비교 기준은 doc4 제외, 기존 `data/embedding`과 새 `data/embedding_metadata`이다.
- 전체 성능은 대부분 개선되었다.
  - `Recall@1`: `0.2500` -> `0.3667`
  - `Recall@3`: `0.4833` -> `0.5250`
  - `Recall@5`: `0.5167` -> `0.5750`
  - `Hit@5`: `0.6167` -> `0.7083`
  - `MRR@5`: `0.3658` -> `0.4492`
  - `nDCG@5`: `0.3866` -> `0.4663`
  - `Complete Recall@5`: `0.2000` -> `0.3333`
- `canon_direct`, `canon_paraphrase`, `psychology_multihop`은 뚜렷하게 좋아졌다.
- 특히 `Recall@1`, `MRR@5`, `nDCG@5`가 함께 오른 점은 정답 청크가 Top-5에만 들어온 것이 아니라 더 앞순위로 올라왔다는 의미다.
- 반대로 `psychology_interpretation`, `trait_generalization`은 일부 하락했다.
  - `psychology_interpretation` `Recall@5`: `0.7500` -> `0.6000`
  - `trait_generalization` `Recall@5`: `0.6000` -> `0.4000`
- 현재 판단: metadata Chroma 재생성은 성공이며 앞으로 기본 실험 기준으로 사용할 가치가 있다.
- 다음 개선 방향은 Chroma 데이터 자체보다 검색 전략에 있다.
  - 사실 질문은 doc1 우선
  - 심리/성격/해석 질문은 doc2/doc3 우선
  - 질문 유형 기반 라우팅 또는 문서별 가중치 적용
  - `--per-doc-k 10` 실험으로 doc2/doc3 후보가 충분히 올라오는지 확인

### 청크 구성 실험 계획

- 앞으로 검색기 평가에서는 기본적으로 doc4를 제외한다.
- category 기반 가중치는 실제 자율 대화형 챗봇 사용 방식과 어긋나므로 우선 적용하지 않는다.
- 청크 실험은 한 번에 여러 요소를 바꾸지 않고, `embedding_metadata` 결과를 baseline으로 두고 하나씩 비교한다.
- baseline 결과 파일:
  - `storymate/평가자료/results/retriever_eval_metadata_summary.json`
- baseline 주요 지표:
  - 전체 `Recall@5`: `0.5750`
  - 전체 `MRR@5`: `0.4492`
  - 전체 `nDCG@5`: `0.4663`
  - 전체 `Complete Recall@5`: `0.3333`
  - `psychology_interpretation` `Recall@5`: `0.6000`
  - `trait_generalization` `Recall@5`: `0.4000`

| 실험 ID | 실험 이름 | 변경 범위 | 예측 | 근거 | 결과 파일 | 전체 Recall@5 | 전체 MRR@5 | 전체 nDCG@5 | psychology_interpretation Recall@5 | trait_generalization Recall@5 | 판단 |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| baseline | metadata Chroma | 평가셋 Corpus 기준 Chroma 재생성, metadata 포함 | 기준값 | `chunk_id`, `doc_id` metadata로 정답 청크 매칭이 안정화됨 | `retriever_eval_metadata_summary.json` | `0.5750` | `0.4492` | `0.4663` | `0.6000` | `0.4000` | 기준 |
| chunk_larger | doc2/doc3 큰 청크 | doc2/doc3의 작은 청크를 3~4개 수준의 큰 청크로 병합 | 해석/성격 질문 개선 예상, MRR은 일부 하락 가능 | 심리/성격 질문은 단일 문장보다 넓은 맥락을 요구하고, 현재 doc2/doc3 근거가 분산되어 있을 가능성이 있음 | `storymate/평가자료/result/chunk_experiments/chunk_larger/retriever_eval_summary.json` | `0.6417` | `0.4601` | `0.4872` | `0.8000` | `0.6667` | 채택 후보 |
| chunk_overlap | doc2/doc3 overlap | doc2/doc3 청크 사이에 인접 근거를 일부 중복 포함 | 다중 근거 질문과 해석형 질문 개선 예상, 중복 검색 위험 있음 | 근거가 청크 경계에서 끊기면 필요한 맥락을 함께 검색하지 못하므로 overlap이 완충 역할을 할 수 있음 | `storymate/평가자료/result/chunk_experiments/chunk_overlap/retriever_eval_summary.json` | `0.6167` | `0.4529` | `0.4717` | `0.7000` | `0.4667` | 부분 채택 후보 |
| chunk_qa_style | doc2/doc3 Q-A 근거형 | doc2/doc3 내용을 질문 표현과 답변 근거가 함께 드러나게 재구성 | paraphrase, 심리, 성격 일반화 질문 개선 예상, 해석 과잉 위험 있음 | 사용자 질문은 설명문보다 질문형/원인형 표현에 가까우므로 query와 chunk 표현 간 거리를 줄일 수 있음 | `retriever_eval_chunk_qa_style_summary.json` |  |  |  |  |  | 대기 |
| chunk_doc1_context | doc1 문맥 확장 | doc1 원문 청크에 앞뒤 문맥을 일부 추가 | 사실 질문 유지 또는 소폭 개선, 청크가 길어지면 정확도 하락 가능 | 원문 사실 질문은 이미 강하므로 후순위 실험으로 두고, 사건 전후 맥락이 필요한 질문에만 효과가 있을 수 있음 | `storymate/평가자료/result/chunk_experiments/doc1_context/retriever_eval_summary.json` | `0.5833` | `0.4374` | `0.4646` | `0.5500` | `0.4000` | 보류 |

#### 실험 판단 기준

- 성공 기준:
  - 전체 `Recall@5`가 `0.5750` 이상일 것
  - 전체 `MRR@5`가 `0.4492` 이상일 것
  - `psychology_interpretation` `Recall@5`가 `0.6000`보다 올라갈 것
  - `trait_generalization` `Recall@5`가 `0.4000`보다 올라갈 것
- 방어 기준:
  - `canon_direct`, `canon_paraphrase`의 `Recall@5`가 `0.9000` 아래로 크게 떨어지지 않을 것
  - 전체 `nDCG@5`가 크게 하락하지 않을 것
- 우선순위:
  - 1순위: `chunk_larger`
  - 2순위: `chunk_overlap`
  - 3순위: `chunk_qa_style`
  - 4순위: `chunk_doc1_context`

#### 청크 실험 실행 스크립트

- 추가 스크립트: `storymate/평가자료/scripts/run_chunk_experiment.py`
- 결과 저장 디렉토리: `storymate/평가자료/result/chunk_experiments/`
- 실험용 Chroma 저장 위치: `storymate/운수좋은날/김첨지/data/chunk_experiments/{experiment}/`
- 지원하는 자동 실험:
  - `chunk_larger`: doc2/doc3 인접 청크를 묶어 더 큰 청크로 생성
  - `chunk_overlap`: doc2/doc3 인접 청크를 겹치게 묶어 생성
  - `chunk_qa_style`: doc2/doc3을 별도 QA-style 청크 데이터로 교체
  - `doc1_context`: doc1 원문 청크에 앞뒤 문맥을 포함해 생성
- `chunk_qa_style`은 사람이 작성한 `storymate/평가자료/data/chunk_qa_style_chunks.json`을 읽어 실험용 Chroma를 생성한다.
- 청크를 병합하거나 overlap하면 새 `chunk_id`가 생기므로, metadata에 `source_chunk_ids`를 저장하고 평가 시 원본 정답 청크와 겹치는지로 채점한다.
- `nDCG@5` 계산에서 같은 원본 청크가 여러 실험 청크에 중복 포함될 때 중복 가산되지 않도록 수정했다.

#### 청크 실험 결과 해석

- 가장 좋은 실험은 `chunk_larger`이다.
  - 전체 `Recall@5`: `0.5750` -> `0.6417`
  - 전체 `MRR@5`: `0.4492` -> `0.4601`
  - 전체 `nDCG@5`: `0.4663` -> `0.4872`
  - `psychology_interpretation` `Recall@5`: `0.6000` -> `0.8000`
  - `trait_generalization` `Recall@5`: `0.4000` -> `0.6667`
- `chunk_larger`는 원래 목표였던 해석형 질문과 성격 일반화 질문을 모두 크게 개선했고, 전체 순위 품질도 baseline보다 좋아졌다.
- `chunk_overlap`은 전체 성능은 개선되었고 `psychology_multihop`과 `Complete Recall@5`에 강점이 있다.
  - 전체 `Recall@5`: `0.5750` -> `0.6167`
  - 전체 `Complete Recall@5`: `0.3333` -> `0.4667`
  - `psychology_multihop` `Recall@5`: `0.8667` -> `0.9333`
- 다만 `chunk_overlap`은 `trait_generalization` 개선 폭이 작고, `chunk_larger`보다 전체 Recall/MRR/nDCG가 낮다.
- `doc1_context`는 `psychology_multihop`에는 강하지만 전체 `MRR@5`가 baseline보다 낮고, 원래 개선 목표였던 `psychology_interpretation`은 오히려 하락했다.
- 현재 판단:
  - 1순위 채택 후보는 `chunk_larger`
  - 다중 근거 회수율을 더 중시할 경우 `chunk_overlap`을 추가 비교
  - `doc1_context`는 현 단계에서 기본 청크 전략으로 채택하지 않는다.

### 검색기 baseline 갱신 결정

- 새 검색기 baseline을 `chunk_larger`로 갱신한다.
- baseline 기준 파일:
  - `storymate/평가자료/result/chunk_experiments/current_baseline.json`
- 이전 baseline인 `embedding_metadata`는 비교용으로 유지한다.
- 앞으로 검색기 실험은 `chunk_larger` 결과와 비교한다.
- 실제 `chatbot_sql.py` 검색 로직에는 아직 반영하지 않는다.
- 반영을 보류하는 이유:
  - 현재 결과는 검색기 평가셋 기준 개선이다.
  - 실제 챗봇 답변 품질은 생성 단계, 프롬프트, 대화 기록과 함께 평가해야 한다.
  - 검색 성능이 올라도 답변 품질이 반드시 같은 폭으로 좋아진다고 단정할 수 없다.
- 다음 단계:
  - `chunk_larger` Chroma를 사용한 챗봇 답변 평가 경로를 준비한다.
  - 기존 검색기 사용 답변과 `chunk_larger` 검색기 사용 답변을 같은 평가 데이터로 비교한다.
  - 답변 평가에서도 개선이 확인되면 실제 챗봇 검색 DB를 교체하거나 설정으로 선택 가능하게 만든다.

### 다음 검색기 실험: chunk_larger + per-doc-k 10

- 목적:
  - `chunk_larger` 청크 구성은 유지하고, 각 문서 DB에서 가져오는 후보 수만 `5`에서 `10`으로 늘린다.
  - 좋은 후보가 Top-5 최종 결과에 들어오기 전에 검색 후보군에서 누락되는지 확인한다.
- 변경 사항:
  - `storymate/평가자료/scripts/run_chunk_experiment.py`에 `--result-name` 옵션을 추가했다.
  - 같은 `chunk_larger` Chroma를 사용하더라도 결과를 `chunk_larger_perdoc10`처럼 별도 디렉토리에 저장할 수 있다.
- 결과 저장 예정 위치:
  - `storymate/평가자료/result/chunk_experiments/chunk_larger_perdoc10/`
- 예측:
  - 전체 `Recall@5`는 상승하거나 유지될 가능성이 있다.
  - `Complete Recall@5`는 상승 가능성이 있다.
  - 후보가 많아지면서 최상위 정렬이 흔들리면 `MRR@5`는 소폭 하락할 수 있다.
- 비교 기준:
  - 현재 baseline `chunk_larger`
  - 전체 `Recall@5`: `0.6417`
  - 전체 `MRR@5`: `0.4601`
  - 전체 `nDCG@5`: `0.4872`
  - 전체 `Complete Recall@5`: `0.3333`

#### per-doc-k 실험 기록표

| 실험 ID | 기반 청크 | per-doc-k | 변경 내용 | 예측 | 결과 파일 | 전체 Recall@5 | 전체 MRR@5 | 전체 nDCG@5 | Complete Recall@5 | psychology_multihop Recall@5 | psychology_interpretation Recall@5 | trait_generalization Recall@5 | 판단 |
|---|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| chunk_larger_baseline | chunk_larger | `5` | 현재 검색기 baseline | 기준값 | `storymate/평가자료/result/chunk_experiments/chunk_larger/retriever_eval_summary.json` | `0.6417` | `0.4601` | `0.4872` | `0.3333` | `0.8000` | `0.8000` | `0.6667` | 기준 |
| chunk_larger_perdoc10 | chunk_larger | `10` | 각 문서 DB에서 가져오는 후보 수를 `5`에서 `10`으로 확대 | Recall과 Complete Recall 상승 가능, MRR은 소폭 하락 가능 | `storymate/평가자료/result/chunk_experiments/chunk_larger_perdoc10/retriever_eval_summary.json` | `0.6417` | `0.4601` | `0.4871` | `0.3333` | `0.8000` | `0.8000` | `0.6667` | 변화 없음 |

#### per-doc-k 실험 결과 해석

- `per-doc-k`를 `5`에서 `10`으로 늘렸지만 전체 결과는 baseline과 거의 동일했다.
- 전체 `Recall@5`, `MRR@5`, `Complete Recall@5`가 변하지 않았다.
- 전체 `nDCG@5`만 `0.4872`에서 `0.4871`로 미세하게 달라졌고, 이는 실질적 변화로 보기 어렵다.
- 해석:
  - 현재 `chunk_larger` 구성에서는 문서별 후보 수 `5`만으로도 최종 Top-5에 들어갈 후보가 충분히 확보되고 있다.
  - 검색 성능 병목은 후보 수 부족이 아니라, 청크 구성 또는 최종 정렬 방식에 더 가깝다.
- 판단:
  - `per-doc-k 10`은 채택하지 않는다.
  - 기본값은 `per-doc-k 5`를 유지한다.
  - 다음 실험은 후보 수 확대보다 `chunk_larger + overlap 혼합` 또는 `chunk_qa_style`이 더 유효하다.

### 다음 검색기 실험: chunk_larger + chunk_overlap 혼합

- 목적:
  - `chunk_larger`의 전체 균형을 유지하면서 `chunk_overlap`이 보였던 다중근거 회수율 강점을 일부 가져올 수 있는지 확인한다.
- 변경 사항:
  - `storymate/평가자료/scripts/run_chunk_experiment.py`에 `chunk_larger_overlap` 실험을 추가했다.
  - doc2는 `chunk_larger`처럼 인접 청크를 단순 병합한다.
  - doc3은 인접 청크를 overlap 방식으로 묶는다.
- 실험 근거:
  - `chunk_larger`는 전체 `Recall@5`, `MRR@5`, `nDCG@5`가 가장 좋았다.
  - `chunk_overlap`은 전체 기준으로는 `chunk_larger`보다 낮았지만 `Complete Recall@5`와 `psychology_multihop`에 강점이 있었다.
  - doc3은 성격/특성 근거 성격이 강하므로, overlap으로 인접 특성 근거를 함께 잡는 효과를 기대한다.
- 예측:
  - `Complete Recall@5`가 `chunk_larger`보다 상승할 가능성이 있다.
  - `psychology_multihop`이 개선될 가능성이 있다.
  - `trait_generalization`은 `chunk_larger` 수준을 유지하는 것이 목표다.
  - 중복 후보가 늘면 `MRR@5`가 소폭 하락할 수 있다.

#### chunk_larger_overlap 실험 기록표

| 실험 ID | doc2 구성 | doc3 구성 | 예측 | 결과 파일 | 전체 Recall@5 | 전체 MRR@5 | 전체 nDCG@5 | Complete Recall@5 | psychology_multihop Recall@5 | psychology_interpretation Recall@5 | trait_generalization Recall@5 | 판단 |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| chunk_larger_baseline | larger | larger | 기준값 | `storymate/평가자료/result/chunk_experiments/chunk_larger/retriever_eval_summary.json` | `0.6417` | `0.4601` | `0.4872` | `0.3333` | `0.8000` | `0.8000` | `0.6667` | 기준 |
| chunk_overlap_reference | overlap | overlap | 다중근거 참고값 | `storymate/평가자료/result/chunk_experiments/chunk_overlap/retriever_eval_summary.json` | `0.6167` | `0.4529` | `0.4717` | `0.4667` | `0.9333` | `0.7000` | `0.4667` | 참고 |
| chunk_larger_overlap | larger | overlap | Complete Recall과 multihop 개선, 전체 MRR은 소폭 하락 가능 | `storymate/평가자료/result/chunk_experiments/chunk_larger_overlap/retriever_eval_summary.json` | `0.6083` | `0.4512` | `0.4712` | `0.3333` | `0.8000` | `0.7000` | `0.5333` | 채택 안 함 |

#### chunk_larger_overlap 실험 결과 해석

- `chunk_larger_overlap`은 현재 baseline인 `chunk_larger`보다 전반적으로 낮았다.
  - 전체 `Recall@5`: `0.6417` -> `0.6083`
  - 전체 `MRR@5`: `0.4601` -> `0.4512`
  - 전체 `nDCG@5`: `0.4872` -> `0.4712`
  - `psychology_interpretation` `Recall@5`: `0.8000` -> `0.7000`
  - `trait_generalization` `Recall@5`: `0.6667` -> `0.5333`
- 기대했던 `Complete Recall@5` 개선도 나타나지 않았다.
  - `Complete Recall@5`: `0.3333` -> `0.3333`
- `psychology_multihop`도 baseline과 동일했다.
  - `psychology_multihop` `Recall@5`: `0.8000` -> `0.8000`
- 참고 실험인 `chunk_overlap`은 `Complete Recall@5`와 `psychology_multihop`에서는 강했지만, doc3만 overlap으로 섞은 이번 실험에서는 그 장점이 재현되지 않았다.
- 현재 판단:
  - `chunk_larger_overlap`은 채택하지 않는다.
  - `doc3`에 overlap을 섞는 방식은 현재 평가셋 기준으로 성격/해석 근거 검색을 약화시킨다.
  - baseline은 계속 `chunk_larger`로 유지한다.
  - 다음 실험은 자동 병합보다 `chunk_qa_style`처럼 doc2/doc3 내용 표현을 질문 친화적으로 재구성하는 방향이 더 적절하다.

### 다음 검색기 실험: chunk_qa_style

- 목적:
  - doc2/doc3 청크를 단순 설명문이 아니라 실제 사용자 질문에 가까운 질문-답변 근거형 문장으로 재구성한다.
  - 청크 크기 조정이 아니라 query와 chunk 표현 간 거리를 줄이는 실험이다.
- 변경 사항:
  - QA-style 청크 데이터 파일을 추가했다.
    - `storymate/평가자료/data/chunk_qa_style_chunks.json`
  - `storymate/평가자료/scripts/run_chunk_experiment.py`에 `chunk_qa_style` 실험을 추가했다.
  - doc1은 기존 청크를 유지한다.
  - doc2/doc3은 QA-style 청크로 교체한다.
  - 새 청크 metadata에는 원본 근거 청크 목록을 `source_chunk_ids`로 저장한다.
- 실험 근거:
  - `chunk_larger`는 청크 크기를 키워 해석/성격 질문을 개선했다.
  - 남은 개선 여지는 청크 크기보다 질문 표현과 근거 표현의 의미적 거리일 가능성이 있다.
  - 자유 대화형 챗봇에서는 사용자가 "왜?", "어떤 성격?", "어떻게 봐야 해?"처럼 질문형으로 묻기 때문에 QA-style 표현이 embedding 검색에 유리할 수 있다.
- 예측:
  - `psychology_interpretation`과 `trait_generalization`에서 추가 개선 가능성이 있다.
  - `canon_paraphrase`도 일부 좋아질 수 있다.
  - 반대로 QA-style 문장이 해석을 강하게 압축하므로 원문 근거성과 `MRR@5`가 하락할 위험이 있다.

#### chunk_qa_style 실험 기록표

| 실험 ID | doc1 구성 | doc2 구성 | doc3 구성 | 예측 | 결과 파일 | 전체 Recall@5 | 전체 MRR@5 | 전체 nDCG@5 | psychology_interpretation Recall@5 | trait_generalization Recall@5 | 판단 |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| chunk_larger_baseline | original | larger | larger | 기준값 | `storymate/평가자료/result/chunk_experiments/chunk_larger/retriever_eval_summary.json` | `0.6417` | `0.4601` | `0.4872` | `0.8000` | `0.6667` | 기준 |
| chunk_qa_style | original | qa_style | qa_style | 해석/성격 질문 개선 가능, 원문 근거성과 MRR 하락 위험 | `storymate/평가자료/result/chunk_experiments/chunk_qa_style/retriever_eval_summary.json` | `0.6333` | `0.4740` | `0.4795` | `0.7500` | `0.6000` | 부분 채택 후보 |

#### chunk_qa_style 실험 결과 해석

- `chunk_qa_style`은 현재 baseline인 `chunk_larger`와 비교했을 때 장단점이 갈린다.
  - 전체 `Recall@5`: `0.6417` -> `0.6333`
  - 전체 `MRR@5`: `0.4601` -> `0.4740`
  - 전체 `nDCG@5`: `0.4872` -> `0.4795`
  - 전체 `Complete Recall@5`: `0.3333` -> `0.4667`
- 좋아진 점:
  - 전체 `MRR@5`가 상승했으므로, 맞는 근거를 찾는 경우에는 더 앞순위에 배치하는 경향이 있다.
  - `psychology_multihop`이 개선되었다.
    - `Recall@1`: `0.4000` -> `0.4667`
    - `Recall@5`: `0.8000` -> `0.8667`
    - `Complete Recall@5`: `0.3333` -> `0.4667`
  - `psychology_interpretation`은 `Recall@5`는 하락했지만 `MRR@5`, `nDCG@5`는 상승했다.
    - `Recall@5`: `0.8000` -> `0.7500`
    - `MRR@5`: `0.4700` -> `0.5292`
    - `nDCG@5`: `0.4432` -> `0.4800`
- 나빠진 점:
  - 전체 `Recall@5`와 `nDCG@5`가 baseline보다 낮다.
  - `trait_generalization`이 하락했다.
    - `Recall@5`: `0.6667` -> `0.6000`
    - `MRR@5`: `0.3022` -> `0.2856`
    - `nDCG@5`: `0.4088` -> `0.3782`
  - `voice_example`의 관련 청크 hit가 크게 줄었지만, doc4를 제외하는 현재 검색기 평가 기준에서는 핵심 판단 요소로 보지 않는다.
- 현재 판단:
  - `chunk_qa_style`을 단독 baseline으로 교체하지 않는다.
  - 기존 `chunk_larger`가 전체 Recall, nDCG, trait_generalization에서 더 안정적이다.
  - 다만 QA-style은 MRR, Complete Recall, multihop, 해석형 질문의 순위 품질에 장점이 있으므로 완전 폐기하지 않는다.
  - 다음 실험 후보는 `chunk_larger`를 유지하면서 QA-style 청크를 추가 보조 청크로 함께 넣는 방식이다.

### 다음 검색기 실험: chunk_larger + QA-style 보조 청크 추가

- 목적:
  - `chunk_larger`를 기본 청크로 유지하면서 QA-style 청크를 doc2/doc3에 추가한다.
  - QA-style 단독 교체에서 얻은 `MRR@5`, `Complete Recall@5`, multihop 개선을 가져오면서 `chunk_larger`의 전체 Recall 안정성을 유지할 수 있는지 확인한다.
- 변경 사항:
  - `storymate/평가자료/scripts/run_chunk_experiment.py`에 `chunk_larger_qa_added` 실험을 추가했다.
  - doc1은 기존 청크를 유지한다.
  - doc2/doc3은 `chunk_larger` 청크를 유지하고, `storymate/평가자료/data/chunk_qa_style_chunks.json`의 QA-style 청크를 추가한다.
- 실험 근거:
  - `chunk_larger`는 현재 전체 Recall과 trait_generalization에서 가장 안정적이다.
  - `chunk_qa_style`은 단독 교체 시 전체 Recall은 소폭 하락했지만 MRR과 Complete Recall이 개선되었다.
  - 따라서 교체가 아니라 추가 방식이면 두 장점을 함께 얻을 가능성이 있다.
- 위험:
  - 후보 청크 수가 늘어나면서 QA-style 청크가 기존 좋은 청크를 밀어낼 수 있다.
  - 유사한 의미의 청크가 중복되어 최종 Top-5 다양성이 낮아질 수 있다.

#### chunk_larger_qa_added 실험 기록표

| 실험 ID | doc1 구성 | doc2 구성 | doc3 구성 | 예측 | 결과 파일 | 전체 Recall@5 | 전체 MRR@5 | 전체 nDCG@5 | Complete Recall@5 | psychology_multihop Recall@5 | psychology_interpretation Recall@5 | trait_generalization Recall@5 | 판단 |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| chunk_larger_baseline | original | larger | larger | 기준값 | `storymate/평가자료/result/chunk_experiments/chunk_larger/retriever_eval_summary.json` | `0.6417` | `0.4601` | `0.4872` | `0.3333` | `0.8000` | `0.8000` | `0.6667` | 기준 |
| chunk_qa_style_reference | original | qa_style | qa_style | QA-style 단독 참고값 | `storymate/평가자료/result/chunk_experiments/chunk_qa_style/retriever_eval_summary.json` | `0.6333` | `0.4740` | `0.4795` | `0.4667` | `0.8667` | `0.7500` | `0.6000` | 참고 |
| chunk_larger_qa_added | original | larger + qa_style | larger + qa_style | Recall 유지와 MRR/Complete Recall 개선 기대 | `storymate/평가자료/result/chunk_experiments/chunk_larger_qa_added/retriever_eval_summary.json` | `0.6333` | `0.4824` | `0.4960` | `0.3333` | `0.8000` | `0.8000` | `0.6000` | 부분 채택 후보 |

#### chunk_larger_qa_added 실험 결과 해석

- `chunk_larger_qa_added`는 현재 baseline인 `chunk_larger`와 비교했을 때 전체 Recall은 약간 낮지만, 순위 품질은 더 좋다.
  - 전체 `Recall@5`: `0.6417` -> `0.6333`
  - 전체 `MRR@5`: `0.4601` -> `0.4824`
  - 전체 `nDCG@5`: `0.4872` -> `0.4960`
  - 전체 `Complete Recall@5`: `0.3333` -> `0.3333`
- 좋아진 점:
  - 전체 `Recall@1`: `0.3583` -> `0.4000`
  - 전체 `MRR@5`와 `nDCG@5`가 지금까지 실험 중 가장 좋다.
  - `psychology_interpretation`은 `Recall@5`를 유지하면서 순위 품질이 좋아졌다.
    - `Recall@5`: `0.8000` -> `0.8000`
    - `MRR@5`: `0.4700` -> `0.5283`
    - `nDCG@5`: `0.4432` -> `0.4836`
  - `trait_generalization`은 `Recall@5`는 하락했지만 상위 적중률과 순위 품질이 좋아졌다.
    - `Recall@1`: `0.1333` -> `0.2667`
    - `MRR@5`: `0.3022` -> `0.3667`
    - `nDCG@5`: `0.4088` -> `0.4455`
- 나빠진 점:
  - 전체 `Recall@5`는 baseline보다 소폭 낮다.
  - `trait_generalization` `Recall@5`가 하락했다.
    - `Recall@5`: `0.6667` -> `0.6000`
  - `psychology_multihop`과 `Complete Recall@5`는 기대와 달리 baseline 대비 개선되지 않았다.
- 현재 판단:
  - `chunk_larger_qa_added`는 단순 폐기할 결과가 아니다.
  - 검색 결과 Top-5 안에 정답을 최대한 포함하는 목적이면 `chunk_larger`가 더 낫다.
  - 생성 답변 품질까지 고려하면, 상위 순위 품질이 좋은 `chunk_larger_qa_added`가 더 나을 가능성이 있다.
  - 현 단계에서는 검색기 baseline을 즉시 교체하지 않고, 답변 생성 평가에서 `chunk_larger`와 `chunk_larger_qa_added`를 함께 비교한다.

### 검색기 실험 완료 기준

- 최종 검색기 후보를 1~2개로 확정하면 검색기 실험을 종료하고 챗봇 답변 평가로 넘어간다.
- 현재 후보:
  - `chunk_larger`: 전체 Recall이 가장 안정적인 검색기 후보
  - `chunk_larger_qa_added`: 상위 순위 품질이 가장 좋은 답변 평가 후보
- BM25를 고려하므로 검색기 실험 종료 전에 다음 2가지를 확인한다.
  - BM25 단독이 vector 검색이 놓치는 query를 잡는지 확인
  - BM25가 의미 있으면 Vector+BM25 Hybrid를 1회 평가
- 완료 판단 기준:
  - 전체 `Recall@5`, `MRR@5`, `nDCG@5` 중 2개 이상이 현재 baseline보다 개선되면 baseline 교체 후보로 본다.
  - `Recall@5`가 유지되고 `MRR@5`, `nDCG@5`가 의미 있게 개선되면 답변 평가 후보로 본다.
  - `psychology_interpretation Recall@5 >= 0.8000`, `trait_generalization Recall@5 >= 0.6000`, `canon_direct Recall@5 >= 0.9500`, `canon_paraphrase Recall@5 >= 0.9500`을 방어 기준으로 둔다.

### 다음 검색기 실험: BM25 단독 및 Hybrid

- 목적:
  - dense vector 검색이 놓치는 정확 키워드 기반 query를 BM25가 잡는지 확인한다.
  - BM25가 유의미하면 Vector+BM25 Hybrid가 현재 후보보다 나은지 확인한다.
- 추가 스크립트:
  - `storymate/평가자료/scripts/evaluate_bm25_hybrid.py`
- 결과 저장 디렉토리:
  - `storymate/평가자료/result/bm25_experiments/`
- 실험 방식:
  - BM25 단독은 Chroma 없이 변환된 청크 텍스트만 사용한다.
  - Hybrid는 vector 결과와 BM25 결과를 Reciprocal Rank Fusion 방식으로 합친다.
  - 기본 비교 청크는 현재 baseline인 `chunk_larger`이다.
- 예측:
  - BM25 단독은 전체 성능에서는 vector보다 낮을 가능성이 있다.
  - 대신 설렁탕, 인력거, 돈, 병, 죽음, 욕설, 손찌검, 일제강점기처럼 명시 키워드가 있는 query에서 일부 강점을 보일 수 있다.
  - Hybrid는 BM25가 잡는 정확 키워드 근거를 보완해 `Recall@5` 또는 `nDCG@5`를 올릴 가능성이 있다.

#### BM25/Hybrid 실험 기록표

| 실험 ID | 기반 청크 | 검색 방식 | 예측 | 결과 파일 | 전체 Recall@5 | 전체 MRR@5 | 전체 nDCG@5 | Complete Recall@5 | psychology_interpretation Recall@5 | trait_generalization Recall@5 | 판단 |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| chunk_larger_baseline | chunk_larger | vector | 기준값 | `storymate/평가자료/result/chunk_experiments/chunk_larger/retriever_eval_summary.json` | `0.6417` | `0.4601` | `0.4872` | `0.3333` | `0.8000` | `0.6667` | 기준 |
| chunk_larger_qa_added_reference | chunk_larger_qa_added | vector | 답변 평가 후보 참고값 | `storymate/평가자료/result/chunk_experiments/chunk_larger_qa_added/retriever_eval_summary.json` | `0.6333` | `0.4824` | `0.4960` | `0.3333` | `0.8000` | `0.6000` | 참고 |
| bm25_chunk_larger | chunk_larger | bm25 | 정확 키워드 query 일부 개선 가능, 전체 성능은 하락 가능 | `storymate/평가자료/result/bm25_experiments/chunk_larger_bm25/retriever_eval_summary.json` | `0.6417` | `0.5029` | `0.5140` | `0.2667` | `0.8000` | `0.6667` | 참고 |
| hybrid_chunk_larger | chunk_larger | vector + bm25 | Recall 또는 nDCG 개선 가능 | `storymate/평가자료/result/bm25_experiments/chunk_larger_hybrid/retriever_eval_summary.json` | `0.6667` | `0.5143` | `0.5256` | `0.2667` | `0.9500` | `0.6000` | 검색기 최종 후보 |

#### BM25/Hybrid 실험 결과 해석

- BM25 단독은 예상보다 강했다.
  - 전체 `Recall@5`: `0.6417`로 `chunk_larger` baseline과 동일
  - 전체 `MRR@5`: `0.4601` -> `0.5029`
  - 전체 `nDCG@5`: `0.4872` -> `0.5140`
- BM25 단독의 강점:
  - `canon_direct`에서 상위 순위 품질이 크게 좋아졌다.
    - `Recall@1`: `0.7000` -> `0.8500`
    - `MRR@5`: `0.8142` -> `0.8917`
  - `psychology_interpretation`도 좋아졌다.
    - `Recall@1`: `0.3000` -> `0.5000`
    - `MRR@5`: `0.4700` -> `0.6083`
    - `nDCG@5`: `0.4432` -> `0.5677`
- BM25 단독의 약점:
  - `canon_paraphrase`가 하락했다.
    - `Recall@5`: `0.9500` -> `0.9000`
  - `Complete Recall@5`가 하락했다.
    - `0.3333` -> `0.2667`
- Hybrid는 현재까지 가장 좋은 전체 검색 지표를 보였다.
  - 전체 `Recall@5`: `0.6417` -> `0.6667`
  - 전체 `MRR@5`: `0.4601` -> `0.5143`
  - 전체 `nDCG@5`: `0.4872` -> `0.5256`
  - 전체 `Hit@5`: `0.7500` -> `0.7833`
- Hybrid의 강점:
  - 전체 Recall, MRR, nDCG가 모두 baseline보다 높다.
  - `psychology_interpretation`이 크게 개선되었다.
    - `Recall@5`: `0.8000` -> `0.9500`
    - `MRR@5`: `0.4700` -> `0.6200`
    - `nDCG@5`: `0.4432` -> `0.5704`
  - `psychology_multihop`도 `Recall@5`가 좋아졌다.
    - `0.8000` -> `0.9333`
- Hybrid의 약점:
  - `trait_generalization`은 하락했다.
    - `Recall@5`: `0.6667` -> `0.6000`
  - `Complete Recall@5`도 하락했다.
    - `0.3333` -> `0.2667`
  - `canon_paraphrase`도 `Recall@5` 기준으로는 baseline보다 낮다.
    - `0.9500` -> `0.9000`
- 현재 판단:
  - BM25는 충분히 의미가 있다.
  - Hybrid는 검색기 최종 후보로 올린다.
  - 다만 `Complete Recall@5`, `trait_generalization`, `canon_paraphrase` 방어가 약하므로 바로 최종 baseline으로 확정하기보다 답변 생성 평가 후보로 포함한다.
  - 답변 생성 평가 후보는 `chunk_larger`, `chunk_larger_qa_added`, `hybrid_chunk_larger` 3개로 좁힌다.

### 최종 검색기 실험 결정: Hybrid Top-20 + Reranker Top-5

- 최종 검색기 실험 범위는 reranker까지로 제한한다.
- 최종 실험 구조:
  - doc4 제외
  - `chunk_larger` 청크 사용
  - Vector 검색과 BM25 검색으로 후보 생성
  - Reciprocal Rank Fusion으로 Hybrid Top-20 후보 구성
  - CrossEncoder reranker로 Top-5 재정렬
- 실험 근거:
  - `chunk_larger`는 전체 Recall이 가장 안정적이다.
  - Hybrid는 전체 `Recall@5`, `MRR@5`, `nDCG@5`를 모두 baseline보다 개선했다.
  - reranker는 Top-20 안에 들어온 후보 중 질문과 가장 관련 높은 청크를 Top-5로 다시 고르는 역할을 한다.
  - 따라서 Hybrid는 후보 회수, reranker는 최종 순위 품질 개선을 담당한다.
- 기대 효과:
  - `Recall@5`는 유지 또는 소폭 상승을 기대한다.
  - `MRR@5`, `nDCG@5`, `Recall@1`, `Recall@3` 개선 가능성이 크다.
  - `psychology_interpretation`처럼 의미 판단과 키워드가 함께 필요한 질문에서 효과를 기대한다.
- 위험:
  - reranker가 해석형 문장을 과도하게 선호하면 `trait_generalization`이나 원문 사실 근거가 밀릴 수 있다.
  - 사전학습 reranker 모델이 프로젝트 평가셋에 최적화된 것은 아니므로 전체 Recall이 반드시 오르지는 않는다.
  - 첫 실행 시 reranker 모델 다운로드가 필요할 수 있다.
- 스크립트 변경:
  - `storymate/평가자료/scripts/evaluate_bm25_hybrid.py`에 `--mode rerank`를 추가했다.
  - 기본 reranker 모델은 `BAAI/bge-reranker-v2-m3`이다.
  - `storymate/requirements.txt`에 `sentence-transformers`를 추가했다.

#### 최종 Reranker 실험 기록표

| 실험 ID | 기반 청크 | 후보 생성 | 후보 수 | 최종 선택 | 예측 | 결과 파일 | 전체 Recall@5 | 전체 MRR@5 | 전체 nDCG@5 | Complete Recall@5 | psychology_interpretation Recall@5 | trait_generalization Recall@5 | 판단 |
|---|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| chunk_larger_baseline | chunk_larger | vector | 5 | 5 | 기준값 | `storymate/평가자료/result/chunk_experiments/chunk_larger/retriever_eval_summary.json` | `0.6417` | `0.4601` | `0.4872` | `0.3333` | `0.8000` | `0.6667` | 기준 |
| hybrid_chunk_larger | chunk_larger | vector + bm25 | 10 | 5 | 현재 최강 검색 후보 | `storymate/평가자료/result/bm25_experiments/chunk_larger_hybrid/retriever_eval_summary.json` | `0.6667` | `0.5143` | `0.5256` | `0.2667` | `0.9500` | `0.6000` | 비교 기준 |
| rerank_chunk_larger_top20 | chunk_larger | vector + bm25 + reranker | 20 | 5 | Recall 유지, MRR/nDCG 개선 기대 | `storymate/평가자료/result/bm25_experiments/chunk_larger_rerank_top20/retriever_eval_summary.json` | `0.7083` | `0.5689` | `0.5845` | `0.6000` | `0.9000` | `0.8000` | 최종 검색기 후보 |

#### 최종 Reranker 실험 결과 해석

- `rerank_chunk_larger_top20`은 지금까지의 검색기 실험 중 가장 좋은 결과다.
- 실험 구성:
  - doc4 제외
  - `chunk_larger` 청크 사용
  - Vector + BM25 Hybrid로 Top-20 후보 생성
  - `BAAI/bge-reranker-v2-m3` CrossEncoder reranker로 Top-5 재정렬
- `chunk_larger` baseline 대비:
  - 전체 `Recall@1`: `0.3583` -> `0.4917`
  - 전체 `Recall@3`: `0.5333` -> `0.6167`
  - 전체 `Recall@5`: `0.6417` -> `0.7083`
  - 전체 `MRR@5`: `0.4601` -> `0.5689`
  - 전체 `nDCG@5`: `0.4872` -> `0.5845`
  - 전체 `Complete Recall@5`: `0.3333` -> `0.6000`
- Hybrid 대비:
  - 전체 `Recall@5`: `0.6667` -> `0.7083`
  - 전체 `MRR@5`: `0.5143` -> `0.5689`
  - 전체 `nDCG@5`: `0.5256` -> `0.5845`
  - 전체 `Complete Recall@5`: `0.2667` -> `0.6000`
- 핵심 카테고리:
  - `canon_direct` `Recall@5`: `1.0000`
  - `canon_paraphrase` `Recall@5`: `1.0000`
  - `psychology_multihop` `Recall@5`: `1.0000`
  - `psychology_interpretation` `Recall@5`: `0.9000`
  - `trait_generalization` `Recall@5`: `0.8000`
- 중요한 변화:
  - Hybrid에서 약점이었던 `Complete Recall@5`가 크게 회복되었다.
  - Hybrid에서 하락했던 `trait_generalization`도 baseline보다 좋아졌다.
  - `canon_paraphrase`도 Hybrid의 하락 문제를 해결하고 `1.0000`까지 상승했다.
- 현재 판단:
  - 검색기 최종 후보는 `rerank_chunk_larger_top20`으로 확정할 수 있다.
  - 검색기 실험 단계는 목표를 달성했다.
  - 다음 단계는 이 검색기를 실제 챗봇 답변 생성 평가에 연결하는 것이다.

### 최종 검색기 챗봇 답변 평가 연결

- 최종 검색기를 `ChatBot`에서 선택적으로 사용할 수 있게 연결했다.
- 변경 파일:
  - `storymate/final_retriever.py`
  - `storymate/chatbot_sql.py`
  - `storymate/평가자료/scripts/evaluate_chatbot.py`
  - `storymate/평가자료/scripts/compare_chatbot_eval.py`
- `ChatBot`에 `retrieval_mode` 옵션을 추가했다.
  - `default`: 기존 Chroma retriever 방식
  - `final_rerank`: `chunk_larger` + Vector/BM25 Hybrid Top-20 + reranker Top-5 방식
- `evaluate_chatbot.py`에 `--retrieval-mode final_rerank` 옵션을 추가했다.
- 처음 평가 결과와 최종 검색기 평가 결과를 비교하기 위해 `compare_chatbot_eval.py`를 추가했다.
- 비교 기준:
  - baseline: `storymate/평가자료/results/eval_results.jsonl`
  - final rerank: `storymate/평가자료/results/eval_results_final_rerank.jsonl`
- 주의:
  - 기존 챗봇 평가 요약은 자동 체크 중심이다.
  - 따라서 비교 스크립트는 형식 준수, 길이, 금지 표현, 필수 포함어 같은 자동 rubric을 비교한다.
  - 답변의 의미적 품질은 이후 별도 LLM/사람 평가가 필요하다.

### 최종 검색기 챗봇 답변 평가 결과

- 비교 기준:
  - baseline: `storymate/평가자료/results/eval_results.jsonl`
  - final rerank: `storymate/평가자료/results/eval_results_final_rerank.jsonl`
  - comparison: `storymate/평가자료/results/eval_comparison_final_rerank.json`
- 두 평가 모두 전체 200개 샘플이며 에러는 없다.
- 최종 검색기 구성:
  - `chunk_larger`
  - Vector + BM25 Hybrid Top-20
  - `BAAI/bge-reranker-v2-m3` Reranker Top-5

| 항목 | baseline | final_rerank | 변화 | 해석 |
|---|---:|---:|---:|---|
| `format_ok` | `0.9550` | `0.9500` | `-0.0050` | 거의 동일, 1개 샘플 차이 |
| `length_ok` | `0.9600` | `0.9600` | `0.0000` | 변화 없음 |
| `no_emoji_ok` | `0.9950` | `0.9950` | `0.0000` | 변화 없음 |
| `no_hidden_reasoning_ok` | `0.9900` | `0.9900` | `0.0000` | 변화 없음 |
| `no_ai_or_prompt_meta_ok` | `0.9900` | `0.9900` | `0.0000` | 변화 없음 |
| `must_include_ok` | `0.0850` | `0.1200` | `+0.0350` | 필수 근거 포함이 개선됨 |
| `must_not_claim_ok` | `1.0000` | `1.0000` | `0.0000` | 금지 주장 방어 유지 |

#### 카테고리별 주요 변화

- `canon_fact`의 `must_include_ok`가 크게 개선되었다.
  - `0.3500` -> `0.5250`
  - 기존 14/40개 통과에서 21/40개 통과로 증가했다.
  - 최종 검색기가 사실 질문에서 필요한 근거 단어를 더 잘 공급한 것으로 볼 수 있다.
- `conversation_memory`의 `format_ok`와 `length_ok`가 하락했다.
  - `format_ok`: `0.9500` -> `0.9000`
  - `length_ok`: `0.9500` -> `0.9000`
  - 검색기 개선과 직접 관련된 의미 품질 하락이라기보다, 답변 길이 조건에서 1개 샘플이 추가 실패한 것으로 보인다.
- `adversarial`의 `length_ok`는 소폭 개선되었다.
  - `0.7600` -> `0.8000`
- `character_psychology`, `character_consistency`, `knowledge_boundary`, `speech_fidelity`의 자동 형식 지표는 사실상 유지되었다.

#### 현재 판단

- 최종 검색기 연결은 답변 자동 평가에서 큰 형식 손상을 만들지 않았다.
- `must_include_ok`가 전체 기준 `+0.0350`, `canon_fact` 기준 `+0.1750` 개선된 점은 의미가 있다.
- 다만 현재 챗봇 평가 스크립트는 의미적 정답성보다 형식/포함어 중심이라, 검색기 성능 개선이 답변 품질에 얼마나 반영되었는지 완전히 판단하기에는 부족하다.
- 다음 단계는 최종 검색기 답변과 baseline 답변의 의미 품질을 비교하는 평가 항목을 추가하는 것이다.
