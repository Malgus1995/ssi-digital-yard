# Stockyard Assignment MIP Formulation

본 문서는 적치장 배정 OR-Tools MIP 모델의 **표기법, 목적함수, 제약조건**만 정리한다.
다음 공장이 당일 수용하는 블록은 공장으로 직행하고, 수용일까지 대기해야 하는
블록만 적치장을 사용한다. 목적함수 값은 화폐 단위가 아닌 가중 비용 점수이다.

## 1. Notation

### 1.1 Sets and indices

| 기호 | 정의 |
| --- | --- |
| $b \in \mathcal{B}$ | 블록 인덱스 |
| $\mathcal{B}^{W}=\{b\in\mathcal{B}:h_b>0\}$ | 적치장 대기 블록 집합 |
| $y \in \mathcal{Y}$ | 적치장 인덱스 |
| $\mathcal{Y}_b \subseteq \mathcal{Y}$ | 블록 $b$의 후보 적치장 집합 |
| $d \in \mathcal{D}$ | 일(day) 인덱스 |
| $\mathcal{B}^{W}_d$ | 날짜 $d$에 적치 중인 대기 블록 집합 |
| $k \in \mathcal{K}$ | 혼잡도 구간 인덱스 |

블록의 적치 구간은 다음 공장이 수용하는 출고일을 제외한 반개구간이다.

$$
b \in \mathcal{B}^{W}_d
\iff
d_b^{\mathrm{in}} \le d < d_b^{\mathrm{out}}
$$

### 1.2 Parameters

| 기호 | 단위 | 정의 |
| --- | ---: | --- |
| $l_b, w_b$ | m | 블록 $b$의 가로·세로 길이 |
| $z_b$ | m | 블록 $b$의 높이 |
| $v_b=l_bw_bz_b$ | m³ | 블록 $b$의 체적 |
| $h_b=\max(0,d_b^{\mathrm{out}}-d_b^{\mathrm{in}})$ | day | 적치장 대기일 수 |
| $\alpha$ | - | 작업 여유 면적 계수 |
| $a_b=\alpha l_bw_b$ | m² | 블록 $b$의 유효 점유 면적 |
| $A_y$ | m² | 적치장 $y$의 총면적 |
| $\rho_y$ | - | 적치장 $y$의 사용 가능 면적 비율 |
| $C_y=\rho_yA_y$ | m² | 적치장 $y$의 사용 가능 면적 |
| $\bar{u}$ | - | 허용 최대 이용률 |
| $D_{by}$ | m | 입고 공장→적치장→출고 공장 총 이동거리 |
| $q_b$ | - | 블록 크기 계수 |
| $T_{by}$ | score | 운송 비용 점수 |
| $H_{by}$ | score | 내부 취급 위험 점수 |
| $R_{by}$ | rank | first-fit 후보 순위 |
| $\theta_k$ | - | 혼잡 구간 $k$의 이용률 임계값 |
| $\gamma_k$ | - | 혼잡 구간 $k$의 한계 비용 기울기 |
| $w_T,w_H,w_R,w_U,w_P$ | - | 비용항별 가중치 |

블록 크기, 운송, 내부 취급 점수는 다음과 같다.

$$
q_b=
0.70\frac{l_bw_b}{\operatorname{median}_{i\in\mathcal{B}^{W}}(l_iw_i)}
+0.30\frac{v_b}{\operatorname{median}_{i\in\mathcal{B}^{W}}(v_i)}
$$

$$
T_{by}
=
\frac{D_{by}}{1000}
\left(0.75+0.25q_b\right)
$$

$$
H_{by}
=
h_b
q_b
\left(1+\frac{3}{\max(1,s_y)}\right)
$$

여기서 $s_y$는 적치장 $y$의 lane 수이다.

## 2. Decision variables

| 변수 | 정의 |
| --- | --- |
| $x_{by}\in\{0,1\}$ | 대기 블록 $b\in\mathcal{B}^{W}$를 적치장 $y$에 배정하면 1 |
| $0\le e_{ydk}\le\max(0,(\bar u-\theta_k)C_y)$ | 날짜 $d$, 적치장 $y$에서 임계값 $\theta_k$를 초과한 면적 |
| $0\le p_y\le\bar{u}$ | 계획기간 동안 적치장 $y$의 최대 이용률 |

날짜별 적치 부하는 다음과 같이 정의한다.

$$
L_{yd}
=
\sum_{b\in\mathcal{B}^{W}_d:\,y\in\mathcal{Y}_b}
a_bx_{by}
$$

## 3. Objective function

블록-적치장 배정 비용 계수는 다음과 같다.

$$
c_{by}
=
w_TT_{by}
+w_HH_{by}
+w_RR_{by}
$$

전체 목적함수는 운송, 내부 취급, first-fit 순위 이탈, 일별 혼잡도,
적치장 최대 이용률을 최소화한다.

$$
\begin{aligned}
\min Z
=\;&
\sum_{b\in\mathcal{B}^{W}}
\sum_{y\in\mathcal{Y}_b}
c_{by}x_{by} \\
&+w_U
\sum_{y\in\mathcal{Y}}
\sum_{d\in\mathcal{D}}
\sum_{k\in\mathcal{K}}
\frac{\gamma_k}{1000}e_{ydk} \\
&+w_P\sum_{y\in\mathcal{Y}}p_y
\end{aligned}
\tag{OBJ}
$$

$b\notin\mathcal{B}^{W}$인 직행 블록은 적치장 의사결정변수가 없으며 위
적치장 운영비에는 포함되지 않는다.

## 4. Constraints

### 4.1 Unique assignment

대기일이 양수인 블록만 후보 적치장 중 정확히 한 곳에 배정한다.
대기일이 0인 블록은 다음 공장으로 직행하므로 배정변수를 생성하지 않는다.

$$
\sum_{y\in\mathcal{Y}_b}x_{by}=1
\qquad
\forall b\in\mathcal{B}^{W}
\tag{C1}
$$

### 4.2 Daily capacity

날짜별 점유 면적은 허용 최대 용량을 넘을 수 없다.

$$
L_{yd}\le\bar{u}C_y
\qquad
\forall y\in\mathcal{Y},\ d\in\mathcal{D}
\tag{C2}
$$

### 4.3 Peak utilization

$p_y$는 적치장 $y$의 모든 날짜별 이용률보다 크거나 같다.

$$
L_{yd}\le C_yp_y
\qquad
\forall y\in\mathcal{Y},\ d\in\mathcal{D}
\tag{C3}
$$

### 4.4 Piecewise-linear congestion

임계값 $\theta_k$를 초과하는 점유 면적을 $e_{ydk}$로 측정한다.

$$
L_{yd}-e_{ydk}\le\theta_kC_y
\qquad
\forall y\in\mathcal{Y},\ d\in\mathcal{D},\ k\in\mathcal{K}
\tag{C4}
$$

목적함수가 $e_{ydk}$를 최소화하므로 최적해에서는 다음 관계가 성립한다.

$$
e_{ydk}
=
\max\left(0,L_{yd}-\theta_kC_y\right)
$$

여러 임계값과 증가하는 $\gamma_k$를 사용하여 이용률 증가에 따른 볼록
구간선형 혼잡 비용을 구성한다.

### 4.5 Variable domains

$$
x_{by}\in\{0,1\}
\qquad
\forall b\in\mathcal{B}^{W},\ y\in\mathcal{Y}_b
\tag{C5}
$$

$$
0\le e_{ydk}\le\max(0,(\bar u-\theta_k)C_y)
\qquad
\forall y\in\mathcal{Y},\ d\in\mathcal{D},\ k\in\mathcal{K}
\tag{C6}
$$

$$
0\le p_y\le\bar{u}
\qquad
\forall y\in\mathcal{Y}
\tag{C7}
$$

## 5. Default coefficients

| 항목 | 기본값 |
| --- | ---: |
| $\alpha$ | 1.15 |
| $\rho_y$ | 0.75 |
| $\bar{u}$ | 0.95 |
| $w_T$ | 1.00 |
| $w_H$ | 0.35 |
| $w_R$ | 0.20 |
| $w_U$ | 1.00 |
| $w_P$ | 6.00 |

| $k$ | $\theta_k$ | $\gamma_k$ |
| ---: | ---: | ---: |
| 1 | 0.50 | 2.0 |
| 2 | 0.70 | 6.0 |
| 3 | 0.85 | 18.0 |

## 6. Candidate-domain preprocessing

대기 블록 $b\in\mathcal{B}^{W}$에 대해 다음 조건을 만족하는 적치장만
$\mathcal{Y}_b$의 후보가 될 수 있다.

$$
a_b\le\bar{u}C_y
$$

또한 입고·출고 공장과 적치장 사이의 거리 정보가 모두 존재해야 한다.
구현에서는 실행 규모를 줄이기 위해 적합한 적치장 가운데 가까운 8곳과
용량이 큰 보조 후보 2곳을 유지한다. 이는 MIP 제약식이 아니라 변수 생성 전
후보 축소 단계이다.

## 7. First-fit policy

First-fit은 대기 블록에만 적용하며 하드 제약이 아니다.

- $R_{by}$를 목적함수에 포함하여 우선순위가 낮은 후보에 비용을 부과한다.
- 동일한 순위 기준으로 초기 배정안을 만들고 OR-Tools 해 탐색 힌트로 전달한다.
- 따라서 용량·혼잡도·운송비가 불리하면 솔버는 다른 적치장을 선택할 수 있다.

## 8. Implementation mapping

| 수식 | 구현 |
| --- | --- |
| 후보 집합 및 $T_{by},H_{by},R_{by}$ | [`build_assignment_options`](solver.py#L137) |
| $x_{by}$ | [`create_assignment_variables`](constraints.py#L155) |
| (C1) | [`add_exactly_one_yard_constraints`](constraints.py#L175) |
| $L_{yd}$ | [`build_daily_active_terms`](constraints.py#L193) |
| (C2)–(C4), (C6)–(C7) | [`add_daily_capacity_and_congestion_constraints`](constraints.py#L209) |
| (OBJ) | [`set_minimum_operating_cost_objective`](constraints.py#L284) |
| first-fit 초기해 | [`apply_first_fit_hint`](solver.py#L248) |
