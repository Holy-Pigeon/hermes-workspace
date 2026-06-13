--
-- PostgreSQL database dump
--

\restrict cv7R3htcNtcesxBY57E9aLh2StNySckv2mxF9ywzJepbN65JFevOix8aZj2NiwX

-- Dumped from database version 15.18
-- Dumped by pg_dump version 15.18

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.set_updated_at() OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: rule_versions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.rule_versions (
    id bigint NOT NULL,
    version character varying(32) NOT NULL,
    effective_date date DEFAULT CURRENT_DATE NOT NULL,
    change_summary text NOT NULL,
    document_path text DEFAULT 'docs/selection_rules.md'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.rule_versions OWNER TO postgres;

--
-- Name: TABLE rule_versions; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.rule_versions IS '筛选规则文档版本记录。';


--
-- Name: rule_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.rule_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.rule_versions_id_seq OWNER TO postgres;

--
-- Name: rule_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.rule_versions_id_seq OWNED BY public.rule_versions.id;


--
-- Name: stale_stock_picks_for_thesis_review; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.stale_stock_picks_for_thesis_review AS
SELECT
    NULL::bigint AS stock_pick_id,
    NULL::character varying(32) AS stock_code,
    NULL::character varying(128) AS stock_name,
    NULL::character varying(32) AS market,
    NULL::date AS selected_date,
    NULL::numeric(18,4) AS selected_price,
    NULL::character varying(128) AS sector,
    NULL::numeric(8,2) AS expected_upside_pct,
    NULL::character varying(32) AS stock_status,
    NULL::bigint AS thesis_count,
    NULL::timestamp with time zone AS oldest_thesis_validity_checked_at,
    NULL::timestamp with time zone AS newest_thesis_validity_checked_at,
    NULL::bigint AS stale_thesis_count;


ALTER TABLE public.stale_stock_picks_for_thesis_review OWNER TO postgres;

--
-- Name: stock_pick_reviews; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.stock_pick_reviews (
    id bigint NOT NULL,
    stock_pick_id bigint NOT NULL,
    review_date date DEFAULT CURRENT_DATE NOT NULL,
    current_price numeric(18,4),
    price_change_pct numeric(8,2),
    review_summary text NOT NULL,
    action character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT stock_pick_reviews_action_check CHECK (((action)::text = ANY ((ARRAY['keep'::character varying, 'upgrade'::character varying, 'downgrade'::character varying, 'close'::character varying, 'invalidate'::character varying])::text[])))
);


ALTER TABLE public.stock_pick_reviews OWNER TO postgres;

--
-- Name: TABLE stock_pick_reviews; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.stock_pick_reviews IS '股票池复盘表，用于记录每周/每次复盘结论。';


--
-- Name: stock_pick_reviews_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.stock_pick_reviews_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.stock_pick_reviews_id_seq OWNER TO postgres;

--
-- Name: stock_pick_reviews_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.stock_pick_reviews_id_seq OWNED BY public.stock_pick_reviews.id;


--
-- Name: stock_picks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.stock_picks (
    id bigint NOT NULL,
    stock_code character varying(32) NOT NULL,
    stock_name character varying(128) NOT NULL,
    market character varying(32),
    selected_date date DEFAULT CURRENT_DATE NOT NULL,
    selected_price numeric(18,4) NOT NULL,
    currency character varying(16) DEFAULT 'CNY'::character varying,
    sector character varying(128) NOT NULL,
    expected_upside_pct numeric(8,2) NOT NULL,
    target_price numeric(18,4),
    target_market_cap numeric(24,4),
    conviction_rating character varying(32),
    score numeric(5,2),
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT stock_picks_conviction_rating_check CHECK (((conviction_rating)::text = ANY ((ARRAY['high'::character varying, 'medium_high'::character varying, 'medium'::character varying, 'watch'::character varying])::text[]))),
    CONSTRAINT stock_picks_expected_upside_pct_check CHECK ((expected_upside_pct >= (0)::numeric)),
    CONSTRAINT stock_picks_score_check CHECK (((score IS NULL) OR ((score >= (0)::numeric) AND (score <= (100)::numeric)))),
    CONSTRAINT stock_picks_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'watching'::character varying, 'closed'::character varying, 'invalidated'::character varying])::text[])))
);


ALTER TABLE public.stock_picks OWNER TO postgres;

--
-- Name: TABLE stock_picks; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.stock_picks IS '每日筛选出的股票池主表。每条记录代表某只股票在某个日期被纳入股票池。';


--
-- Name: COLUMN stock_picks.stock_code; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_picks.stock_code IS '股票代码，例如 09992.HK、AAPL、300750.SZ。';


--
-- Name: COLUMN stock_picks.stock_name; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_picks.stock_name IS '股票名称。';


--
-- Name: COLUMN stock_picks.selected_date; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_picks.selected_date IS '入选日期。';


--
-- Name: COLUMN stock_picks.selected_price; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_picks.selected_price IS '入选价格。';


--
-- Name: COLUMN stock_picks.sector; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_picks.sector IS '所在板块/行业方向。';


--
-- Name: COLUMN stock_picks.expected_upside_pct; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_picks.expected_upside_pct IS '预期涨幅百分比，例如 50.00 表示预期上涨 50%。';


--
-- Name: stock_picks_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.stock_picks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.stock_picks_id_seq OWNER TO postgres;

--
-- Name: stock_picks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.stock_picks_id_seq OWNED BY public.stock_picks.id;


--
-- Name: stock_theses; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.stock_theses (
    id bigint NOT NULL,
    stock_pick_id bigint NOT NULL,
    thesis_title character varying(256) NOT NULL,
    thesis_detail text NOT NULL,
    still_valid boolean DEFAULT true NOT NULL,
    status character varying(32) DEFAULT 'valid'::character varying NOT NULL,
    key_supporting_data text NOT NULL,
    invalidation_condition text,
    last_checked_date date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    validity_last_checked_at timestamp with time zone,
    validity_check_count integer DEFAULT 0 NOT NULL,
    last_validation_summary text,
    last_supporting_data_snapshot text,
    next_check_due_at timestamp with time zone,
    CONSTRAINT stock_theses_status_check CHECK (((status)::text = ANY ((ARRAY['valid'::character varying, 'needs_review'::character varying, 'invalidated'::character varying])::text[])))
);


ALTER TABLE public.stock_theses OWNER TO postgres;

--
-- Name: TABLE stock_theses; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.stock_theses IS '股票入选核心论点子表。一只股票可以对应多个核心论点，每个论点需要持续维护状态。';


--
-- Name: COLUMN stock_theses.still_valid; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_theses.still_valid IS '该核心论点是否仍然成立。';


--
-- Name: COLUMN stock_theses.key_supporting_data; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_theses.key_supporting_data IS '关键支撑数据，例如业绩增速、订单、估值、行业价格、资金流等。';


--
-- Name: COLUMN stock_theses.invalidation_condition; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_theses.invalidation_condition IS '该论点的失效条件。';


--
-- Name: COLUMN stock_theses.validity_last_checked_at; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_theses.validity_last_checked_at IS '最近一次验证该论点有效性的时间，用于判断最近七天是否更新过论点有效性。';


--
-- Name: COLUMN stock_theses.validity_check_count; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_theses.validity_check_count IS '论点有效性验证次数。';


--
-- Name: COLUMN stock_theses.last_validation_summary; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_theses.last_validation_summary IS '最近一次论点有效性验证摘要。';


--
-- Name: COLUMN stock_theses.last_supporting_data_snapshot; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_theses.last_supporting_data_snapshot IS '最近一次验证时使用的关键支撑数据快照。';


--
-- Name: COLUMN stock_theses.next_check_due_at; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.stock_theses.next_check_due_at IS '下一次建议检查时间。';


--
-- Name: stock_theses_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.stock_theses_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.stock_theses_id_seq OWNER TO postgres;

--
-- Name: stock_theses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.stock_theses_id_seq OWNED BY public.stock_theses.id;


--
-- Name: rule_versions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rule_versions ALTER COLUMN id SET DEFAULT nextval('public.rule_versions_id_seq'::regclass);


--
-- Name: stock_pick_reviews id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_pick_reviews ALTER COLUMN id SET DEFAULT nextval('public.stock_pick_reviews_id_seq'::regclass);


--
-- Name: stock_picks id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_picks ALTER COLUMN id SET DEFAULT nextval('public.stock_picks_id_seq'::regclass);


--
-- Name: stock_theses id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_theses ALTER COLUMN id SET DEFAULT nextval('public.stock_theses_id_seq'::regclass);


--
-- Data for Name: rule_versions; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.rule_versions VALUES (1, 'v0.1', '2026-05-29', '初始版本：一年内 50%+ 潜在涨幅候选股筛选框架、打分模型、股票池维护规则。', 'docs/selection_rules.md', '2026-05-29 17:20:38.137405+08');
INSERT INTO public.rule_versions VALUES (2, 'v0.2', '2026-05-29', '增加论点有效性最近检查时间、检查次数、验证摘要、支撑数据快照和待复盘视图，用于每日 17 点复核最近七天未更新论点的股票。', 'docs/selection_rules.md', '2026-05-29 17:32:51.69432+08');
INSERT INTO public.rule_versions VALUES (3, 'v0.3', '2026-05-30', '明确50%+空间只是入选条件，不能作为核心论据；新增护城河、利润可持续性和非线性外推约束；要求每只股票至少4条核心论点，并按新规则重写2026-05-30三只股票论据。', 'docs/selection_rules.md', '2026-05-30 15:39:23.485511+08');
INSERT INTO public.rule_versions VALUES (4, 'v0.4', '2026-05-31', '按真实买入决策标准升级：所有核心论据必须量化，包含当前基数、目标假设、桥接测算、情景/概率和失效阈值；纯定性论据不合格，并按新规则重写2026-05-30三只股票论据。', 'docs/selection_rules.md', '2026-05-30 15:56:43.517192+08');
INSERT INTO public.rule_versions VALUES (8, 'v0.6', '2026-06-01', '重大修正：区分50%潜在上涨空间和50%概率加权期望收益；新增高位拥挤降权、周期股利润拆分、库存收益折价规则；仅牛市情景有50%空间但概率加权不足25%的股票只能标为watching。', 'docs/selection_rules.md', '2026-06-01 15:13:07.389463+08');


--
-- Data for Name: stock_pick_reviews; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.stock_pick_reviews VALUES (1, 1, '2026-06-01', 505.8000, -8.25, 'v0.6严格复评：江波龙仍有存储周期和企业级存储逻辑，但当前利润高度受DRAM/NAND涨价、库存收益和补库周期影响，且此前按Q1高景气利润年化至140亿元并给25x PE过于激进。按概率加权口径，牛市仍可能+50%以上，但中性多为估值消化，熊市存在-30%~-50%回撤，期望收益显著低于50%。从50%期望收益池降级。', 'downgrade', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_pick_reviews VALUES (2, 2, '2026-06-01', 305.0000, -6.84, 'v0.6严格复评：佰维存储高弹性仍在，但更偏高位周期情绪票。Q1高增长包含存储涨价、库存和补库收益，不能按长期利润资本化；股价和市场预期已较充分，回撤风险大于江波龙。牛市有+50%可能，但概率加权期望明显低于50%。从50%期望收益池降级。', 'downgrade', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_pick_reviews VALUES (3, 3, '2026-06-01', 179.4000, 3.46, 'v0.6严格复评：泡泡玛特基本面仍强，海外/IP/利润率逻辑尚未失效；但当前价较入选价上涨后，相对目标价260-265港元的空间低于或接近50%，且原概率加权期望仅约20%。更适合高质量观察，不满足一年期50%概率加权期望收益。', 'downgrade', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_pick_reviews VALUES (4, 4, '2026-06-01', 1130.0000, -2.68, 'v0.6严格复评：中际旭创仍是AI光模块核心资产，但此前自身情景测算概率加权期望仅约23%，50%空间主要来自牛市情景。公司处高位高热度赛道，市场预期拥挤，需Q2-Q3持续兑现。按新规则不再作为50%期望收益active标的。', 'downgrade', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_pick_reviews VALUES (5, 5, '2026-06-01', 116.0000, -1.78, 'v0.6严格复评：康方生物核心资产和管线逻辑仍有价值，但原概率加权期望约19%，上涨50%依赖依沃西海外/商业化多个节点同时顺利兑现。二元临床和估值折现风险较高，不满足50%概率加权期望收益。', 'downgrade', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_pick_reviews VALUES (6, 22, '2026-06-01', 679.8200, -5.36, 'v0.6严格复评：新易盛800G/1.6T逻辑强，当前价回落后目标空间仍可超过50%；但过去涨幅巨大、AI光模块拥挤度高，且Q1利润环比下滑，60x PE假设容错率低。重新按高位拥挤折扣后，概率加权期望不应维持在50%以上，降为观察。', 'downgrade', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_pick_reviews VALUES (7, 23, '2026-06-01', 122.5100, -7.93, 'v0.6严格复评：沪电股份AI PCB逻辑较实，当前价回落后目标价200元的表观空间超过50%，但TTM PE约60倍、现金流偏弱，目标PE 67.6x需业绩持续超预期支撑。按更保守基准目标和熊市概率修正后，概率加权期望不足50%，降为观察。', 'downgrade', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_pick_reviews VALUES (8, 24, '2026-06-01', 80.5500, 7.62, 'v0.6严格复评：信达生物产品收入高增、玛仕度肽和肿瘤产品组合逻辑仍有效；但当前价格已高于入选价，距118港元目标空间约46.5%，且创新药仍有医保、商业化和临床/估值波动风险。不满足50%概率加权期望收益，降为观察。', 'downgrade', '2026-06-01 15:11:31.741104+08');


--
-- Data for Name: stock_picks; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.stock_picks VALUES (20, '09926', '康方生物', 'HKEX', '2026-05-31', 118.1000, 'HKD', '创新药/出海药企-PD-1/VEGF双抗', 52.41, 180.0000, 1658.0000, 'medium_high', 82.00, 'closed', '按 selection_rules v0.4 入选。50%+空间仅是必要条件。核心买入假设为商业化销售2026E约45-60亿元人民币、依沃西全球权益风险调整价值约700-950亿港元、其他产品/管线约300-450亿港元，现金和平台溢价约150-250亿港元；熊/基准/牛目标价约85/145/180港元，概率25%/45%/30%，概率加权目标价约140.5港元，期望收益约19.0%。若商业化销售增速低于25%或依沃西海外关键临床失败，降级。研究型股票池，不构成投资建议。
[系统修正 2026-05-31] 因每日新入库股票与既有股票池重叠，保留该代码最早一条 active/watching 记录，本条重复入库记录改为 closed，避免活跃股票池重复。', '2026-05-31 08:03:38.842982+08', '2026-05-31 13:24:45.001375+08');
INSERT INTO public.stock_picks VALUES (6, '09992', '泡泡玛特', 'HKEX', '2026-05-30', 173.4000, 'HKD', '全球化消费品牌-潮玩/IP出海', 52.83, 265.0000, 3555.0000, 'medium_high', 84.00, 'closed', '按 selection_rules v0.4 入选。50%+空间仅是必要条件。核心买入假设为2026E收入520-650亿元人民币、净利170-210亿元人民币、净利率32%左右，给予约20-25x PE。熊/基准/牛目标价约125/220/265港元，概率25%/45%/30%，概率加权目标价约209.75港元，期望收益约21.2%。若海外收入增速低于30%、净利率低于28%或库存周转恶化，降级。研究型股票池，不构成投资建议。
[系统修正 2026-05-31] 因每日新入库股票与既有股票池重叠，保留该代码最早一条 active/watching 记录，本条重复入库记录改为 closed，避免活跃股票池重复。', '2026-05-30 08:05:42.078313+08', '2026-05-31 13:24:45.001375+08');
INSERT INTO public.stock_picks VALUES (1, '301308', '江波龙', 'SZSE ChiNext', '2026-05-29', 551.2900, 'CNY', '国产半导体/存储模组与企业级存储', 50.07, 827.4500, 350000000000.0000, 'high', 86.00, 'watching', '按selection_rules v0.2筛选：存储上行周期+AI服务器带动企业级存储需求；腾讯行情2026-05-29收盘价551.29元、总市值约2332.29亿元。目标市值3500亿元，对应目标价约827.45元，隐含约50.1%空间。核心风险：存储价格回落、存货跌价、客户订单波动。公开数据快照：2025年净利润14.23亿元同比+185.41%；2026Q1营收逼近100亿元，净利润38.62亿元，同比+2644.05%，毛利率超过50%。', '2026-05-29 17:46:23.700562+08', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_picks VALUES (2, '688525', '佰维存储', 'SSE STAR Market', '2026-05-29', 327.3700, 'CNY', '国产半导体/存储芯片与先进封测', 55.70, 509.8300, 240000000000.0000, 'medium_high', 84.00, 'watching', '按selection_rules v0.2筛选：存储价格上行与AI端侧/服务器存储需求共振。腾讯行情2026-05-29收盘价327.37元、总市值约1541.38亿元。目标市值2400亿元，对应目标价约509.83元，隐含约55.7%空间。公开数据快照：2026Q1净利润约28.99亿元，同比增幅约921%–1086%；存储概念112家公司Q1合计归母净利润约283.54亿元，同比大幅增长。', '2026-05-29 17:46:23.700562+08', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_picks VALUES (3, '09992', '泡泡玛特', 'HKEX', '2026-05-29', 173.4000, 'HKD', '全球化消费品牌/潮玩IP零售', 50.51, 260.9900, 350000000000.0000, 'high', 85.00, 'watching', '按selection_rules v0.2筛选：全球化消费品牌方向，IP矩阵与海外渠道扩张仍在验证。腾讯行情2026-05-29收盘价173.40港元、总市值约2325.37亿港元。目标市值3500亿港元，对应目标价约260.99港元，隐含约50.5%空间。公开数据快照：2025年营收371.2亿元人民币，同比+184.7%；经调整净利润130.8亿元，同比+284.5%；2026Q1整体收益同比+75%–80%，中国+100%–105%，美洲+55%–60%，欧洲及其他+60%–65%。', '2026-05-29 17:46:23.700562+08', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_picks VALUES (4, '300308', '中际旭创', 'SZSE ChiNext', '2026-05-30', 1161.1600, 'CNY', 'AI算力链-高速光模块/CPO/1.6T', 50.71, 1750.0000, 19300.0000, 'medium_high', 86.00, 'watching', '按 selection_rules v0.4 入选。50%+空间仅是必要条件，核心买入假设为：2026E收入约900-1050亿元、归母净利约285-330亿元、净利率维持31%左右；按熊/基准/牛三情景目标价约930/1500/1750元，概率25%/45%/30%，概率加权目标价约1435元，相对1161.16元期望收益约23.6%，牛市空间50.7%。若Q2-Q3单季净利低于60亿元或净利率低于25%，降级。研究型股票池，不构成投资建议。', '2026-05-30 08:05:42.078313+08', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_picks VALUES (21, '09992', '泡泡玛特', 'HKEX', '2026-05-31', 173.4000, 'HKD', '全球化消费品牌-潮玩/IP出海', 52.83, 265.0000, 3555.0000, 'medium_high', 84.00, 'closed', '按 selection_rules v0.4 入选。50%+空间仅是必要条件。核心买入假设为2026E收入520-650亿元人民币、净利170-210亿元人民币、净利率32%左右，给予约20-25x PE。熊/基准/牛目标价约125/220/265港元，概率25%/45%/30%，概率加权目标价约209.75港元，期望收益约21.2%。若海外收入增速低于30%、净利率低于28%或库存周转恶化，降级。研究型股票池，不构成投资建议。
[系统修正 2026-05-31] 因每日新入库股票与既有股票池重叠，保留该代码最早一条 active/watching 记录，本条重复入库记录改为 closed，避免活跃股票池重复。', '2026-05-31 08:03:38.842982+08', '2026-05-31 13:24:45.001375+08');
INSERT INTO public.stock_picks VALUES (19, '300308', '中际旭创', 'SZSE ChiNext', '2026-05-31', 1161.1600, 'CNY', 'AI算力链-高速光模块/CPO/1.6T', 50.71, 1750.0000, 19300.0000, 'medium_high', 86.00, 'closed', '按 selection_rules v0.4 入选。50%+空间仅是必要条件，核心买入假设为：2026E收入约900-1050亿元、归母净利约285-330亿元、净利率维持31%左右；按熊/基准/牛三情景目标价约930/1500/1750元，概率25%/45%/30%，概率加权目标价约1435元，相对1161.16元期望收益约23.6%，牛市空间50.7%。若Q2-Q3单季净利低于60亿元或净利率低于25%，降级。研究型股票池，不构成投资建议。
[系统修正 2026-05-31] 因每日新入库股票与既有股票池重叠，保留该代码最早一条 active/watching 记录，本条重复入库记录改为 closed，避免活跃股票池重复。', '2026-05-31 08:03:38.842982+08', '2026-05-31 13:24:45.001375+08');
INSERT INTO public.stock_picks VALUES (5, '09926', '康方生物', 'HKEX', '2026-05-30', 118.1000, 'HKD', '创新药/出海药企-PD-1/VEGF双抗', 52.41, 180.0000, 1658.0000, 'medium_high', 82.00, 'watching', '按 selection_rules v0.4 入选。50%+空间仅是必要条件。核心买入假设为商业化销售2026E约45-60亿元人民币、依沃西全球权益风险调整价值约700-950亿港元、其他产品/管线约300-450亿港元，现金和平台溢价约150-250亿港元；熊/基准/牛目标价约85/145/180港元，概率25%/45%/30%，概率加权目标价约140.5港元，期望收益约19.0%。若商业化销售增速低于25%或依沃西海外关键临床失败，降级。研究型股票池，不构成投资建议。', '2026-05-30 08:05:42.078313+08', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_picks VALUES (22, '300502', '新易盛', 'A股/深交所创业板', '2026-06-01', 718.3400, 'CNY', 'AI算力链/高速光模块', 55.60, 1118.4000, 11140.0000, 'medium_high', 83.00, 'watching', '规则v0.5筛选：AI算力资本开支持续增长，800G/1.6T光模块放量。目标测算：2026E EPS 18.64元 × 60倍PE = 1118.4元；当前约718.34元，对应约55.6%空间。情景：牛75倍PE/1398元(30%)，基准60倍PE/1118元(50%)，熊45倍PE/839元(20%)；概率加权目标约1126元，期望收益约56.8%。风险：Q1环比利润-13.25%、汇兑与物料瓶颈。', '2026-06-01 08:04:54.231408+08', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_picks VALUES (23, '002463', '沪电股份', 'A股/深交所', '2026-06-01', 133.0600, 'CNY', 'AI算力链/高速PCB', 50.31, 200.0000, 3840.0000, 'medium_high', 78.00, 'watching', '规则v0.5筛选：高速运算服务器、AI交换机和汽车电子拉动高端PCB需求。目标测算：2026E EPS 2.96元 × 67.6倍PE = 200元；当前约133.06元，对应约50.3%空间。情景：牛230元(25%)，基准200元(50%)，熊105元(25%)；概率加权约183.75元，期望收益约38.1%，但基准空间达标。', '2026-06-01 08:04:54.231408+08', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_picks VALUES (24, '01801', '信达生物', '港股/HKEX', '2026-06-01', 74.8500, 'HKD', '创新药/GLP-1/肿瘤商业化', 57.65, 118.0000, 1920.0000, 'medium_high', 82.00, 'watching', '规则v0.5筛选：公司2026Q1产品收入超过38亿元、同比超过50%，叠加玛仕度肽商业化、肿瘤TKI医保放量和多适应症获批。目标测算：按目标价118港元、股本约16.3亿股测算目标市值约1920亿港元；当前74.85港元，对应约57.7%空间。情景：牛138港元(25%)，基准118港元(50%)，熊60港元(25%)；概率加权108.5港元，期望收益约45.0%。', '2026-06-01 08:04:54.231408+08', '2026-06-01 15:11:31.741104+08');
INSERT INTO public.stock_picks VALUES (25, '002384', '东山精密', 'A股/深交所', '2026-06-02', 191.7500, 'CNY', 'AI算力链/AI PCB+光通信', 56.45, 300.0000, 5496.0000, 'medium_high', 82.00, 'active', '规则v0.6筛选：非当前active/watching重叠代码。2026-06-01收盘191.75元、总市值3512.11亿元；目标价300元/目标市值约5496亿元。目标测算采用2027E EPS约7.00元、目标PE约42.9倍；情景为牛360元(30%)、基准300元(50%)、熊150元(20%)，概率加权目标约286元，概率加权期望收益约49.2%。主要约束：近期涨幅和拥挤度较高，资产负债率63.69%、商誉47.69亿元需持续复核。', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08');
INSERT INTO public.stock_picks VALUES (26, '601138', '工业富联', 'A股/上交所', '2026-06-02', 73.7500, 'CNY', 'AI算力链/AI服务器与高速网络设备', 62.71, 120.0000, 23832.0000, 'medium_high', 80.00, 'active', '规则v0.6筛选：非当前active/watching重叠代码。2026-06-01附近现价约73.75元、市值约1.46万亿元；目标价120元/目标市值约2.38万亿元。目标测算：2026E EPS 3.10元×38.7倍PE=120元，PEG约0.52；情景为牛135元(25%)、基准120元(45%)、熊60元(30%)，概率加权目标约105.75元，概率加权期望收益约43.4%。风险：市值大、机构平均目标价约73.39元，需靠Q2/Q3上修验证预期差。', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08');


--
-- Data for Name: stock_theses; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.stock_theses VALUES (1, 1, '存储景气周期带来利润弹性', '公司作为国内存储模组龙头，受益于DRAM/NAND价格上行、AI服务器和企业级SSD需求增长；一季度利润已显示强周期弹性。', true, 'valid', '2025年净利润14.23亿元，同比+185.41%；2026Q1营收逼近100亿元，归母净利润38.62亿元，同比+2644.05%，毛利率超过50%；行业公开监测显示DRAM/NAND价格快速上行。', '若后续两个季度存储现货/合约价格连续回落，或公司季度毛利率跌回30%以下且库存跌价准备明显上升，则该论点失效。', '2026-05-29', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', 1, '2026Q1利润大幅超过2025全年利润的一半以上，说明价格周期与产品结构升级已传导到利润表。', '数据快照：腾讯行情收盘价551.29元、市值约2332.29亿元；2026Q1净利润38.62亿元，同比+2644.05%；2025净利润14.23亿元，同比+185.41%。', '2026-06-05 17:46:23.700562+08');
INSERT INTO public.stock_theses VALUES (2, 1, '估值未完全反映全年利润年化', '按2026年利润中枢120–140亿元测算，给予25倍PE对应3000–3500亿元合理市值；相较当前约2332亿元市值具备约29%–50%+空间，取上沿目标3500亿元。', true, 'valid', '当前市值约2332.29亿元；若2026净利润按Q1高景气并保守折减至140亿元，25倍PE对应3500亿元目标市值，目标价约827.45元，较551.29元约+50.1%。', '若2026年滚动净利润预期下修至80亿元以下，或行业景气导致合理PE降至20倍以下，则目标市值测算失效。', '2026-05-29', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', 1, '当前PE口径约42.9倍，但按2026高景气利润年化明显下降，PEG相对利润增速仍有吸引力。', '测算快照：目标市值3500亿元=140亿元净利润×25倍PE；当前市值约2332.29亿元；目标价827.45元。', '2026-06-05 17:46:23.700562+08');
INSERT INTO public.stock_theses VALUES (3, 1, '国产替代与企业级产品结构升级', '公司从消费级存储向企业级SSD、嵌入式存储和高端模组升级，国产供应链安全需求与AI数据中心扩容共同提高中高端产品占比。', true, 'valid', '公开资料显示2026Q1营收逼近100亿元且毛利率超过50%，显著高于传统模组低毛利水平，反映产品结构和价格周期共振。', '若企业级产品订单不及预期、客户集中度导致议价受损，或高毛利率无法维持两个季度以上，则该论点失效。', '2026-05-29', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', 1, '本次筛选时，高毛利率与高利润率已验证结构升级并非仅收入规模扩张。', '快照：2026Q1营收近100亿元、净利润38.62亿元、毛利率>50%；所在方向符合规则文档“国产半导体/存储链”。', '2026-06-05 17:46:23.700562+08');
INSERT INTO public.stock_theses VALUES (4, 2, 'Q1利润爆发验证周期上行', '公司处于存储芯片与模组景气反转核心环节，价格上涨和出货恢复推动利润高弹性释放。', true, 'valid', '公开信息显示2026Q1净利润约28.99亿元，同比增幅约921%–1086%；存储概念112家公司Q1合计归母净利润283.54亿元，同比大幅增长。', '若公司后续季度净利润环比下滑超过40%，或DRAM/NAND价格回落导致毛利率显著下降，则周期弹性论点失效。', '2026-05-29', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', 1, '本次入选时，单季利润已接近/超过多数历史年度水平，行业层面亦有广泛利润改善。', '快照：2026Q1净利润约28.99亿元；腾讯行情收盘价327.37元、市值约1541.38亿元、PE约39倍。', '2026-06-05 17:46:23.700562+08');
INSERT INTO public.stock_theses VALUES (5, 2, '目标市值测算满足50%+空间', '若2026年全年利润达到80亿元左右，按30倍PE给予2400亿元目标市值；相对当前1541亿元市值仍有约55.7%空间。', true, 'valid', '当前市值约1541.38亿元；目标市值2400亿元=80亿元净利润×30倍PE；对应目标价约509.83元，较327.37元约+55.7%。', '若全年净利润预期降至55亿元以下，或估值中枢因周期担忧降至25倍以下，则目标价需要下修。', '2026-05-29', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', 1, '以Q1约28.99亿元利润为基础，即使后续季度环比回落，全年80亿元仍具备可验证路径。', '测算快照：目标价509.83元；当前价327.37元；目标市值2400亿元；当前市值1541.38亿元。', '2026-06-05 17:46:23.700562+08');
INSERT INTO public.stock_theses VALUES (6, 2, 'AI与端侧存储需求提供催化', 'AI服务器、AI PC/手机、车载与工业存储需求提高高容量、高性能产品占比，若库存周期继续向上，公司盈利可继续超预期。', true, 'valid', '行业公开信息显示2026年以来江波龙、佰维存储、兆易创新等国产存储龙头持续刷新高点；美光、SK海力士等上修资本开支和存储价格，DRAM/NAND价格快速上涨。', '若AI终端拉货低于预期、客户库存重新积压，或公司应收/存货周转恶化，则该催化论点失效。', '2026-05-29', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', 1, '本次筛选时，行业资金趋势、业绩数据和产品价格三者同向，符合规则要求的“明确催化剂”。', '快照：2026Q1行业112家存储概念公司合计净利润283.54亿元；公司Q1净利润约28.99亿元；板块资金热度高。', '2026-06-05 17:46:23.700562+08');
INSERT INTO public.stock_theses VALUES (7, 3, '全球化IP商业化仍高增长', '泡泡玛特的核心预期差在于市场担心单一IP热度回落，但公司多IP矩阵与海外渠道扩张仍驱动高收入增长。', true, 'valid', '2025年营收371.2亿元，同比+184.7%；经调整净利润130.8亿元，同比+284.5%；2026Q1整体收益同比+75%–80%，中国+100%–105%，美洲+55%–60%，欧洲及其他+60%–65%。', '若2026年任一连续两个季度整体收入增速低于40%，或海外收入增速低于30%且库存折扣扩大，则该论点失效。', '2026-05-29', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', 1, '本次入选时，2026Q1各区域仍保持高增长，海外和中国市场并未同步失速。', '快照：2026Q1整体收益同比+75%–80%；中国+100%–105%；美洲+55%–60%；欧洲及其他+60%–65%；2025经调整净利130.8亿元。', '2026-06-05 17:46:23.700562+08');
INSERT INTO public.stock_theses VALUES (8, 3, '利润率提升与规模效应支撑估值', '高毛利IP产品、直营渠道与供应链规模效应使利润增速显著高于收入增速，合理估值可高于普通消费零售。', true, 'valid', '2025年毛利率由2024年的66.8%提升至72.1%，提高5.3个百分点；2025经调整净利润130.8亿元，同比+284.5%，显著快于营收+184.7%。', '若毛利率跌破65%，或销售费用率大幅上升导致经调整净利率连续两个季度下滑超过5个百分点，则该论点失效。', '2026-05-29', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', 1, '本次入选时，公司仍处利润率上行和规模摊薄阶段，估值消化依赖利润继续高增。', '快照：2025营收371.2亿元、经调整净利130.8亿元、毛利率72.1%；当前市值约2325.37亿港元。', '2026-06-05 17:46:23.700562+08');
INSERT INTO public.stock_theses VALUES (9, 3, '目标市值具备50%+修复空间', '按2026年经调整净利润约200–220亿元人民币、给予约15–16倍港币口径PE，目标市值3500亿港元；相对当前2325亿港元具备约50.5%空间。', true, 'valid', '当前价173.40港元、市值约2325.37亿港元；目标市值3500亿港元，对应目标价260.99港元；2026Q1收入+75%–80%为全年利润继续增长提供基础。', '若2026年经调整净利润预期下修至170亿元人民币以下，或市场给予消费IP估值降至12倍以下，则目标市值测算失效。', '2026-05-29', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', '2026-05-29 17:46:23.700562+08', 1, '本次测算未采用过高PE，而是以利润高增后的15–16倍估值中枢给出50%+空间。', '测算快照：目标价260.99港元；目标市值3500亿港元；当前价173.40港元；当前市值2325.37亿港元；隐含+50.5%。', '2026-06-05 17:46:23.700562+08');
INSERT INTO public.stock_theses VALUES (85, 23, '估值仍低于电子成长股中位但需以业绩消化', '当前价格约133.06元，TTM PE约59.06倍、扣非PE约60.82倍，低于同页显示的行业中位PE约87.25倍。用2026E EPS 2.96元和目标PE 67.6倍得到200元目标价，估值扩张幅度小于行业中位，主要依靠盈利增长消化。', true, 'valid', '当前股价133.06元；TTM PE 59.06倍；扣非PE 60.82倍；行业中位PE 87.25倍；2026E EPS 2.96元；目标PE 67.6倍。', '若电子/PCB行业中位PE跌破60倍，或公司Forward PE维持高于55倍但2026E利润增速下修至30%以下，则估值修复论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, '当前估值相对行业仍非最高，但高估值要求业绩持续兑现。', '当前股价133.06元；TTM PE 59.06倍；扣非PE 60.82倍；行业中位PE 87.25倍；2026E EPS 2.96元；目标PE 67.6倍。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (79, 22, '800G/1.6T需求带来收入高基数再增长', '2026Q1收入83.38亿元、同比+105.76%，在2025年前三季收入165.05亿元的高基数上继续翻倍，说明海外AI客户资本开支仍在转化为订单。若2026全年收入按季度83.38亿元、92亿元、100亿元、108亿元爬坡，全年收入约383亿元，较2025市场估算约248亿元增长约54%，可支撑高端光模块收入继续放大。', true, 'valid', '2026Q1收入83.38亿元，同比+105.76%；2025前三季收入165.05亿元，同比+221.70%；基准测算2026全年收入约383亿元，季度均值约95.8亿元。', '若未来任一季度收入低于75亿元，或连续2个季度收入同比增速低于50%，或1.6T出货未能在2026H2贡献超过20亿元季度收入，则该收入增长论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, '当前数据仍支持“收入高基数增长+1.6T放量”的入选逻辑。', '2026Q1收入83.38亿元，同比+105.76%；2025前三季收入165.05亿元，同比+221.70%；基准测算2026全年收入约383亿元，季度均值约95.8亿元。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (80, 22, '盈利弹性仍高但需监控环比波动', '2026Q1归母净利润27.80亿元、同比+76.80%，毛利率49.16%、ROE 13.64%，利润率远高于一般电子制造公司。机构一致预测2026净利润185.34亿元、EPS 18.64元，同比约+94.45%；从Q1利润到全年预测需后三季度合计157.54亿元、季度均值52.51亿元，核心依赖1.6T高毛利产品占比提升和费用率摊薄。', true, 'valid', '2026Q1归母净利润27.80亿元，同比+76.80%，环比-13.25%；2026E净利润185.34亿元、EPS 18.64元、同比+94.45%；Q1毛利率49.16%。', '若单季毛利率跌破43%，或2026H1归母净利润低于65亿元，或全年一致预期净利润被下修至150亿元以下，则盈利弹性论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, '盈利同比仍高增，但Q1环比回落需要后续季报验证。', '2026Q1归母净利润27.80亿元，同比+76.80%，环比-13.25%；2026E净利润185.34亿元、EPS 18.64元、同比+94.45%；Q1毛利率49.16%。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (81, 22, '客户与技术认证形成交付壁垒', '高速光模块的关键壁垒在于海外云厂商认证、良率、交付周期和上游器件锁定。公司总股本约9.96亿股、总市值约7035亿元，市场愿意给予65倍TTM PE，反映其已进入全球AI光模块核心供应链。若1.6T产品率先规模交付，产品ASP和单位利润有望维持高于800G阶段的水平。', true, 'valid', '总股本约9.96亿股；当前总市值约7035.52亿元；TTM PE约65.51倍；52周最高733.99元、最低85.84元，资金风险偏好强。', '若海外核心客户订单占比下降导致单季收入环比下降超过20%，或公司公告重要客户认证/交付延迟超过1个季度，或TTM PE压缩至45倍以下且盈利预期同步下修，则供应链壁垒论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, '现有估值和收入规模显示公司仍被定价为核心供应链成员。', '总股本约9.96亿股；当前总市值约7035.52亿元；TTM PE约65.51倍；52周最高733.99元、最低85.84元，资金风险偏好强。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (82, 22, '财务质量可接受但现金流需跟踪', '2026Q1经营现金净流入6.84亿元，虽然低于27.80亿元归母净利润，但仍为正；资产负债率31.04%，没有高杠杆扩张风险。若后续因备货、应收或汇兑导致现金流长期低于利润，将显著削弱高利润质量判断。', true, 'valid', '2026Q1经营现金净流入6.84亿元；归母净利润27.80亿元；现金利润比约24.6%；资产负债率31.04%；毛利率49.16%。', '若连续2个季度经营现金流/净利润低于20%，或资产负债率升至45%以上，或单季汇兑/财务费用损失超过8亿元，则财务质量论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, '当前现金流为正、负债率较低，但现金利润比偏低需复核。', '2026Q1经营现金净流入6.84亿元；归母净利润27.80亿元；现金利润比约24.6%；资产负债率31.04%；毛利率49.16%。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (83, 23, 'AI服务器PCB订单驱动收入加速', '2026Q1公司营业收入62.14亿元、同比+53.91%，增速与AI服务器和高速网络板卡需求同步。若全年按Q1 62.14亿元为底、后续季度环比小幅提升至65/70/75亿元，2026收入约272亿元，较高基数继续增长，支撑利润增速接近50%。', true, 'valid', '2026Q1营业收入62.14亿元，同比+53.91%；2026Q1归母净利润12.42亿元，同比+62.90%；基准测算2026全年收入约272亿元。', '若未来任一季度收入低于55亿元，或AI相关PCB订单导致的收入增速连续2个季度低于30%，或客户交付延迟超过1个季度，则订单驱动论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, 'Q1收入和利润均超过50%增速，符合AI PCB景气验证。', '2026Q1营业收入62.14亿元，同比+53.91%；2026Q1归母净利润12.42亿元，同比+62.90%；基准测算2026全年收入约272亿元。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (84, 23, '利润增长与机构预期具备一致性', '机构对2026年净利润预测57.19亿元、同比+49.63%，EPS 2.96元，较Q1 12.42亿元需后三季度44.77亿元、季度均值14.92亿元，仅比Q1高约20.1%，兑现难度相对可控。若AI高阶板占比继续提升，利润率仍有上行弹性。', true, 'valid', '23家机构预测2026 EPS 2.96元、净利润57.19亿元、同比+49.63%；2026Q1净利润12.42亿元；后三季度隐含季度均值14.92亿元。', '若2026H1净利润低于25亿元，或全年机构一致预期净利润下修至48亿元以下，或单季净利率低于17%，则利润兑现论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, 'Q1利润进度约21.7%，后三季度爬坡要求可量化跟踪。', '23家机构预测2026 EPS 2.96元、净利润57.19亿元、同比+49.63%；2026Q1净利润12.42亿元；后三季度隐含季度均值14.92亿元。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (55, 4, '收入桥接：Q1已完成全年基准收入约20%-22%，后续季度均值决定目标兑现', '买入级判断不是把Q1线性乘4，而是看全年收入桥接。2026Q1收入194.96亿元；若2026E收入目标900-1050亿元，则Q1完成率约18.6%-21.7%，剩余3个季度合计需705-855亿元，单季均值约235-285亿元。这个要求高但与800G放量、1.6T切换和海外AI CAPEX扩张方向一致；若Q2收入能达到230亿元以上，全年900亿元基准收入的可见度显著提高。', true, 'valid', '当前基数：2026Q1营收194.96亿元/+192.12%。目标假设：2026E收入900-1050亿元；剩余季度均值235-285亿元。桥接：900亿元目标需Q2-Q4收入合计705亿元，较Q1单季194.96亿元提升约20.5%；1050亿元牛市目标需Q2-Q4均值285亿元，较Q1提升约46.2%。', '若Q2收入低于210亿元，或连续2个季度收入低于230亿元且无订单延期解释，则全年900亿元收入目标失效，股票应从active降为watching；若Q2-Q3收入同比降至60%以下，则论点失效。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：收入目标不是简单线性外推，基准情景需要Q2-Q4均值235亿元；Q2收入是第一验证点。', '快照：Q1收入194.96亿元；基准全年收入900亿元、牛市1050亿元；Q2验证阈值210/230亿元。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (56, 4, '利润率桥接：全年净利285-330亿元要求净利率不能跌破25%', '目标价1750元背后隐含利润必须兑现。以目标市值19300亿元和60x PE倒推，牛市净利约322亿元；基准情景若给50x PE、目标市值约16500亿元，则需净利约330亿元，或若净利285亿元则需58x PE。因此真实买入需要盯住净利率而不是只看营收。Q1归母净利57.35亿元、净利率29.4%；全年285-330亿元要求Q2-Q4合计227.65-272.65亿元，单季净利均值75.9-90.9亿元。', true, 'valid', '当前基数：Q1归母净利57.35亿元、扣非57.18亿元、净利率29.4%。目标假设：2026E归母净利285-330亿元；Q2-Q4单季均值75.9-90.9亿元。估值桥接：285亿元*50x=14250亿元，对应约1292元；322亿元*60x=19320亿元，对应约1750元。', '若任一后续季度净利低于60亿元，或净利率低于25%，或全年利润预期下修到250亿元以下，则50%牛市空间不再具备买入级确定性，该论点失效。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：净利率29.4%是核心安全垫；目标价能否成立取决于Q2-Q4净利能否从57.35亿元提升到至少75亿元级别。', '快照：Q1净利57.35亿元；Q1净利率29.4%；全年目标净利285-330亿元；净利率失效阈值25%。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (57, 4, '护城河量化：高端产品和客户认证必须体现在净利率、应收/存货和现金流三项指标中', '高速光模块的护城河不能只说“龙头”，必须量化验证。若客户认证、良率和高端产品结构有效，公司应在收入高增时维持较高净利率，并且应收、存货不能明显跑赢收入。Q1净利率29.4%说明当前产品结构有优势；后续若净利率维持25%-30%，且应收/存货增速不持续高于收入增速50个百分点以上，说明利润质量可接受。', true, 'valid', '当前基数：Q1收入194.96亿元、净利57.35亿元、净利率29.4%。护城河量化指标：净利率维持≥25%；收入同比仍≥60%；应收和存货增速不连续2季高于收入增速50pct；经营现金流/净利润年度比值目标≥0.7。', '若净利率连续2个季度低于25%，或经营现金流/净利润年度比值低于0.5，或应收+存货增速连续2季高于收入增速50pct以上，则说明客户/产品护城河未转化为利润质量，该论点失效。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：Q1 29.4%净利率使高端产品护城河暂时成立，但必须用现金流、存货和应收排除渠道压货或价格战。', '快照：Q1净利率29.4%；后续验证阈值：净利率25%、经营现金流/净利润0.7、应收存货增速差50pct。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (58, 4, '情景收益：基准收益不足牛市水平，买入依赖兑现概率和止损阈值', '真实买入不能只看牛市目标1750元。按1161.16元入选价测算：熊市情景净利250亿元、估值40x，对应市值10000亿元、目标价约906-930元，收益约-20%；基准情景净利300亿元、估值55x，对应市值16500亿元、目标价约1495-1500元，收益约+29%；牛市情景净利322亿元、估值60x，对应市值19300亿元、目标价1750元，收益约+50.7%。假设概率25%/45%/30%，概率加权目标价约1435元，期望收益约23.6%，满足买入观察但不是无脑重仓。', true, 'valid', '当前价1161.16元；目标价：熊930/基准1500/牛1750元；概率：25%/45%/30%；概率加权目标价=930*25%+1500*45%+1750*30%=1432.5元，期望收益约23.4%。牛市空间50.7%是入选条件，非单独论据。', '若基准目标价下修到1350元以下，或熊市概率上升到40%以上，或概率加权期望收益低于15%，则不再满足买入级风险收益比，该论点失效。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：该股有50%牛市空间，但真实决策应按23%-24%概率加权收益和-20%熊市风险管理仓位。', '快照：入选价1161.16元；熊/基准/牛目标价930/1500/1750元；概率加权收益约23.4%；失效阈值期望收益15%。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (59, 5, '商业化收入桥接：30.331亿元基数要增长到45-60亿元才支撑平台估值', '康方不能只靠“创新药出海”定性买入。当前可量化基数是2025年商业化销售30.331亿元人民币/+51.48%。若2026E商业化销售达到45-60亿元，对应同比增长约48%-98%；这会把公司从研发期估值切换到产品现金流估值。若只增长到38亿元（+25%），则只能证明基本盘，难以支撑180港元牛市目标。', true, 'valid', '当前基数：2025商业化销售30.331亿元人民币。目标假设：熊38亿元（+25%）、基准45亿元（+48%）、牛60亿元（+98%）。桥接：45亿元目标需新增14.669亿元销售；60亿元需新增29.669亿元。所有已获批产品及适应症纳入医保。', '若2026上半年商业化销售年化低于38亿元，或全年销售预期低于45亿元，或销售费用率上升超过10pct但收入增速低于25%，则该论点失效。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：商业化销售是最硬的基本盘，45亿元是基准买入阈值，60亿元才支持更激进估值。', '快照：2025商业化销售30.331亿元/+51.48%；2026E情景38/45/60亿元；失效阈值38亿元年化。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (66, 6, '情景收益：概率加权收益约21%，海外和利润率决定牛市兑现', '按173.40港元入选价测算，熊市情景净利145亿元、估值约18x，对应目标价约125港元，收益-27.9%；基准情景净利170亿元、估值约22x，对应目标价约220港元，收益+26.9%；牛市情景净利200-210亿元、估值约25x，对应目标价265港元，收益+52.8%。假设概率25%/45%/30%，概率加权目标价约209.75港元，期望收益约21.0%。', true, 'valid', '当前价173.40港元；当前市值约2325.37亿港元；目标价：熊125/基准220/牛265港元；概率25%/45%/30%；概率加权目标价=125*25%+220*45%+265*30%=209.75港元；期望收益约21.0%。牛市目标市值3555亿港元。', '若基准目标价下修到195港元以下，或熊市概率上升到40%以上，或概率加权期望收益低于15%，则该股不应维持active买入级状态。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：泡泡玛特有明确50%牛市空间，但基准收益约27%、期望收益约21%，需要海外收入和净利率同时达标。', '快照：入选价173.40港元；熊/基准/牛125/220/265港元；概率加权收益约21.0%；失效阈值期望收益15%。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (60, 5, '依沃西rNPV测算：全球权益必须贡献700-950亿港元风险调整价值', '依沃西是康方估值的核心变量，必须用风险调整价值而不是“临床差异化”空话描述。简化rNPV框架：若依沃西全球峰值销售对应权益价值在乐观情景可达1500-2000亿港元，按成功概率/折现/分成风险调整后取700-950亿港元；若关键海外临床失败，该部分价值可能降到300-450亿港元。当前总市值约1087.87亿港元，说明市场已计入部分成功，但未完全计入全球化上限。', true, 'valid', '当前基数：2026-05-29市值约1087.87亿港元；核心资产依沃西PD-1/VEGF。目标假设：依沃西风险调整价值熊300-450亿港元、基准700亿港元、牛950亿港元。若叠加商业化产品和其他管线，牛市总目标市值约1658亿港元。', '若依沃西海外关键临床未达主要终点，或注册延后超过12个月，或风险调整价值下修到500亿港元以下，则该论点失效。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：180港元目标价主要取决于依沃西rNPV从当前部分定价提升到700-950亿港元区间。', '快照：当前市值1087.87亿港元；依沃西rNPV情景300-450/700/950亿港元；注册延后12个月为失效阈值。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (61, 5, '管线组合量化：至少2个商业化/临床节点兑现才能降低单一资产风险', '创新药季度利润受研发费用和授权收入确认影响大，因此买入逻辑必须看节点组合。康方已有商业化收入30.331亿元，并有依沃西、卡度尼利等双抗资产。若未来12个月至少2个节点兑现（例如适应症获批、关键临床阳性、BD或销售超预期），则可把单一资产失败概率分散；若只有1个核心资产支撑，则估值折价应提高。', true, 'valid', '当前基数：商业化销售30.331亿元；已获批产品及适应症纳入医保；目标节点数：未来12个月至少2个重大节点。估值假设：其他产品/管线风险调整价值基准300-450亿港元；若节点少于2个，下修至150-250亿港元。', '若未来12个月重大临床/注册/销售/BD节点少于2个，或其他管线风险调整价值下修到200亿港元以下，则该论点失效。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：管线组合不是定性“丰富”，必须用节点数量和风险调整估值约束；2个节点是维持平台估值的最低要求。', '快照：商业化销售30.331亿元；其他管线rNPV基准300-450亿港元；12个月节点阈值≥2个。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (62, 5, '情景收益：概率加权收益约19%，低于中际旭创，仓位应更谨慎', '按118.10港元入选价计算，熊市情景为依沃西进展不及预期、商业化销售仅38亿元，对应目标价约85港元，收益-28%；基准情景商业化45亿元、依沃西rNPV约700亿港元，对应目标价约145港元，收益+22.8%；牛市情景商业化60亿元、依沃西rNPV约950亿港元，对应目标价180港元，收益+52.4%。假设概率25%/45%/30%，概率加权目标价约140.5港元，期望收益约19.0%。', true, 'valid', '当前价118.10港元；目标价：熊85/基准145/牛180港元；概率：25%/45%/30%；概率加权目标价=85*25%+145*45%+180*30%=140.5港元；期望收益约19.0%。当前市值1087.87亿港元，牛市目标市值1658亿港元。', '若基准目标价下修到130港元以下，或熊市概率上升到40%以上，或概率加权期望收益低于15%，则该股不应维持active买入级状态。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：康方仍有50%牛市空间，但概率加权收益约19%，临床二元风险高，评分由85下调至82。', '快照：入选价118.10港元；熊/基准/牛85/145/180港元；概率加权收益19.0%；失效阈值期望收益15%。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (63, 6, '收入桥接：海外收入占比43.8%，2026E收入需达到520-650亿元才支撑目标价', '泡泡玛特不能只讲“全球化品牌”。2025收入371.2亿元，若2026E达到520-650亿元，对应同比增长约40%-75%；其中海外收入占比已达43.8%，即2025海外收入约162.6亿元。若海外继续增长50%，仅海外可新增约81亿元；国内和新品若新增约70-190亿元，则全年收入目标有路径。', true, 'valid', '当前基数：2025收入371.2亿元/+184.7%；海外占比43.8%，估算海外收入约162.6亿元。目标假设：2026E收入熊450亿元（+21%）、基准520亿元（+40%）、牛650亿元（+75%）。桥接：基准520亿元需新增148.8亿元；若海外+50%贡献约81.3亿元，剩余需国内/新品贡献约67.5亿元。', '若海外收入增速连续2个季度低于30%，或2026E收入预期低于500亿元，或渠道库存周转天数较上年增加超过30%，则该论点失效。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：全球化不是口号，海外收入162.6亿元基数和50%增长假设可解释基准收入520亿元路径。', '快照：2025收入371.2亿元；海外占比43.8%≈162.6亿元；2026E收入情景450/520/650亿元。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (64, 6, '利润桥接：目标估值要求2026E净利至少170亿元，净利率需维持28%-32%', '2025净利润约128-130亿元，若2026E净利170-210亿元，对应同比约31%-64%。这不是线性外推，而是收入增长、IP高毛利和规模效应共同作用。若收入520亿元、净利率32.7%，净利约170亿元；若收入650亿元、净利率32.3%，净利约210亿元。若净利率跌破28%，即便收入520亿元，净利仅约146亿元，目标价需要明显下修。', true, 'valid', '当前基数：2025净利润约128-130亿元；2025收入371.2亿元，估算净利率约34.5%-35.0%。目标假设：2026E净利熊145亿元、基准170亿元、牛210亿元；对应收入520亿元时净利率32.7%，收入650亿元时净利率32.3%。', '若净利率低于28%，或2026E净利预期下修至150亿元以下，或毛利率连续2个季度下滑超过5pct，则该论点失效。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：目标价265港元需要170-210亿元净利区间支撑；净利率28%是硬止损线。', '快照：2025净利128-130亿元；净利率约34.5%-35.0%；2026E净利情景145/170/210亿元；失效阈值150亿元/28%。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (65, 6, 'IP护城河量化：单一爆款风险必须用非单一IP占比、新品转化率和库存指标验证', '泡泡玛特最大风险是Labubu等爆款生命周期，因此护城河不能只说“IP矩阵”。量化验证应看：非单一IP收入占比是否维持在50%以上，新品首发售罄率是否保持高位，库存周转是否不恶化。若单一IP贡献过高且库存上升，利润会在1-2个季度内快速回落。', true, 'valid', '当前基数：2025收入371.2亿元、海外收入约162.6亿元、净利约128-130亿元。护城河目标指标：非最大IP收入占比≥50%；新品首发售罄率/补货转化保持高位；库存周转天数同比增加不超过30%；毛利率下滑不超过5pct。', '若最大单一IP收入占比超过50%且连续2个季度新品转化率下降，或库存周转天数同比增加超过30%，或毛利率下滑超过5pct，则该论点失效。', '2026-05-30', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', '2026-05-30 15:58:40.549655+08', 1, '本次量化复核认为：IP矩阵必须经得起数据检验；库存和非单一IP占比是防止利润突然下滑的关键指标。', '快照：收入371.2亿元；净利128-130亿元；海外约162.6亿元；护城河阈值：非单一IP≥50%、库存周转恶化≤30%、毛利率下滑≤5pct。', '2026-06-06 15:58:40.549655+08');
INSERT INTO public.stock_theses VALUES (67, 19, '收入桥接：Q1已完成全年基准收入约20%-22%，后续季度均值决定目标兑现', '买入级判断不是把Q1线性乘4，而是看全年收入桥接。2026Q1收入194.96亿元；若2026E收入目标900-1050亿元，则Q1完成率约18.6%-21.7%，剩余3个季度合计需705-855亿元，单季均值约235-285亿元。这个要求高但与800G放量、1.6T切换和海外AI CAPEX扩张方向一致；若Q2收入能达到230亿元以上，全年900亿元基准收入的可见度显著提高。', true, 'valid', '当前基数：2026Q1营收194.96亿元/+192.12%。目标假设：2026E收入900-1050亿元；剩余季度均值235-285亿元。桥接：900亿元目标需Q2-Q4收入合计705亿元，较Q1单季194.96亿元提升约20.5%；1050亿元牛市目标需Q2-Q4均值285亿元，较Q1提升约46.2%。', '若Q2收入低于210亿元，或连续2个季度收入低于230亿元且无订单延期解释，则全年900亿元收入目标失效，股票应从active降为watching；若Q2-Q3收入同比降至60%以下，则论点失效。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：收入目标不是简单线性外推，基准情景需要Q2-Q4均值235亿元；Q2收入是第一验证点。', '快照：Q1收入194.96亿元；基准全年收入900亿元、牛市1050亿元；Q2验证阈值210/230亿元。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (68, 19, '利润率桥接：全年净利285-330亿元要求净利率不能跌破25%', '目标价1750元背后隐含利润必须兑现。以目标市值19300亿元和60x PE倒推，牛市净利约322亿元；基准情景若给50x PE、目标市值约16500亿元，则需净利约330亿元，或若净利285亿元则需58x PE。因此真实买入需要盯住净利率而不是只看营收。Q1归母净利57.35亿元、净利率29.4%；全年285-330亿元要求Q2-Q4合计227.65-272.65亿元，单季净利均值75.9-90.9亿元。', true, 'valid', '当前基数：Q1归母净利57.35亿元、扣非57.18亿元、净利率29.4%。目标假设：2026E归母净利285-330亿元；Q2-Q4单季均值75.9-90.9亿元。估值桥接：285亿元*50x=14250亿元，对应约1292元；322亿元*60x=19320亿元，对应约1750元。', '若任一后续季度净利低于60亿元，或净利率低于25%，或全年利润预期下修到250亿元以下，则50%牛市空间不再具备买入级确定性，该论点失效。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：净利率29.4%是核心安全垫；目标价能否成立取决于Q2-Q4净利能否从57.35亿元提升到至少75亿元级别。', '快照：Q1净利57.35亿元；Q1净利率29.4%；全年目标净利285-330亿元；净利率失效阈值25%。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (69, 19, '护城河量化：高端产品和客户认证必须体现在净利率、应收/存货和现金流三项指标中', '高速光模块的护城河不能只说“龙头”，必须量化验证。若客户认证、良率和高端产品结构有效，公司应在收入高增时维持较高净利率，并且应收、存货不能明显跑赢收入。Q1净利率29.4%说明当前产品结构有优势；后续若净利率维持25%-30%，且应收/存货增速不持续高于收入增速50个百分点以上，说明利润质量可接受。', true, 'valid', '当前基数：Q1收入194.96亿元、净利57.35亿元、净利率29.4%。护城河量化指标：净利率维持≥25%；收入同比仍≥60%；应收和存货增速不连续2季高于收入增速50pct；经营现金流/净利润年度比值目标≥0.7。', '若净利率连续2个季度低于25%，或经营现金流/净利润年度比值低于0.5，或应收+存货增速连续2季高于收入增速50pct以上，则说明客户/产品护城河未转化为利润质量，该论点失效。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：Q1 29.4%净利率使高端产品护城河暂时成立，但必须用现金流、存货和应收排除渠道压货或价格战。', '快照：Q1净利率29.4%；后续验证阈值：净利率25%、经营现金流/净利润0.7、应收存货增速差50pct。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (70, 19, '情景收益：基准收益不足牛市水平，买入依赖兑现概率和止损阈值', '真实买入不能只看牛市目标1750元。按1161.16元入选价测算：熊市情景净利250亿元、估值40x，对应市值10000亿元、目标价约906-930元，收益约-20%；基准情景净利300亿元、估值55x，对应市值16500亿元、目标价约1495-1500元，收益约+29%；牛市情景净利322亿元、估值60x，对应市值19300亿元、目标价1750元，收益约+50.7%。假设概率25%/45%/30%，概率加权目标价约1435元，期望收益约23.6%，满足买入观察但不是无脑重仓。', true, 'valid', '当前价1161.16元；目标价：熊930/基准1500/牛1750元；概率：25%/45%/30%；概率加权目标价=930*25%+1500*45%+1750*30%=1432.5元，期望收益约23.4%。牛市空间50.7%是入选条件，非单独论据。', '若基准目标价下修到1350元以下，或熊市概率上升到40%以上，或概率加权期望收益低于15%，则不再满足买入级风险收益比，该论点失效。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：该股有50%牛市空间，但真实决策应按23%-24%概率加权收益和-20%熊市风险管理仓位。', '快照：入选价1161.16元；熊/基准/牛目标价930/1500/1750元；概率加权收益约23.4%；失效阈值期望收益15%。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (71, 20, '商业化收入桥接：30.331亿元基数要增长到45-60亿元才支撑平台估值', '康方不能只靠“创新药出海”定性买入。当前可量化基数是2025年商业化销售30.331亿元人民币/+51.48%。若2026E商业化销售达到45-60亿元，对应同比增长约48%-98%；这会把公司从研发期估值切换到产品现金流估值。若只增长到38亿元（+25%），则只能证明基本盘，难以支撑180港元牛市目标。', true, 'valid', '当前基数：2025商业化销售30.331亿元人民币。目标假设：熊38亿元（+25%）、基准45亿元（+48%）、牛60亿元（+98%）。桥接：45亿元目标需新增14.669亿元销售；60亿元需新增29.669亿元。所有已获批产品及适应症纳入医保。', '若2026上半年商业化销售年化低于38亿元，或全年销售预期低于45亿元，或销售费用率上升超过10pct但收入增速低于25%，则该论点失效。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：商业化销售是最硬的基本盘，45亿元是基准买入阈值，60亿元才支持更激进估值。', '快照：2025商业化销售30.331亿元/+51.48%；2026E情景38/45/60亿元；失效阈值38亿元年化。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (78, 21, '情景收益：概率加权收益约21%，海外和利润率决定牛市兑现', '按173.40港元入选价测算，熊市情景净利145亿元、估值约18x，对应目标价约125港元，收益-27.9%；基准情景净利170亿元、估值约22x，对应目标价约220港元，收益+26.9%；牛市情景净利200-210亿元、估值约25x，对应目标价265港元，收益+52.8%。假设概率25%/45%/30%，概率加权目标价约209.75港元，期望收益约21.0%。', true, 'valid', '当前价173.40港元；当前市值约2325.37亿港元；目标价：熊125/基准220/牛265港元；概率25%/45%/30%；概率加权目标价=125*25%+220*45%+265*30%=209.75港元；期望收益约21.0%。牛市目标市值3555亿港元。', '若基准目标价下修到195港元以下，或熊市概率上升到40%以上，或概率加权期望收益低于15%，则该股不应维持active买入级状态。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：泡泡玛特有明确50%牛市空间，但基准收益约27%、期望收益约21%，需要海外收入和净利率同时达标。', '快照：入选价173.40港元；熊/基准/牛125/220/265港元；概率加权收益约21.0%；失效阈值期望收益15%。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (72, 20, '依沃西rNPV测算：全球权益必须贡献700-950亿港元风险调整价值', '依沃西是康方估值的核心变量，必须用风险调整价值而不是“临床差异化”空话描述。简化rNPV框架：若依沃西全球峰值销售对应权益价值在乐观情景可达1500-2000亿港元，按成功概率/折现/分成风险调整后取700-950亿港元；若关键海外临床失败，该部分价值可能降到300-450亿港元。当前总市值约1087.87亿港元，说明市场已计入部分成功，但未完全计入全球化上限。', true, 'valid', '当前基数：2026-05-29市值约1087.87亿港元；核心资产依沃西PD-1/VEGF。目标假设：依沃西风险调整价值熊300-450亿港元、基准700亿港元、牛950亿港元。若叠加商业化产品和其他管线，牛市总目标市值约1658亿港元。', '若依沃西海外关键临床未达主要终点，或注册延后超过12个月，或风险调整价值下修到500亿港元以下，则该论点失效。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：180港元目标价主要取决于依沃西rNPV从当前部分定价提升到700-950亿港元区间。', '快照：当前市值1087.87亿港元；依沃西rNPV情景300-450/700/950亿港元；注册延后12个月为失效阈值。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (73, 20, '管线组合量化：至少2个商业化/临床节点兑现才能降低单一资产风险', '创新药季度利润受研发费用和授权收入确认影响大，因此买入逻辑必须看节点组合。康方已有商业化收入30.331亿元，并有依沃西、卡度尼利等双抗资产。若未来12个月至少2个节点兑现（例如适应症获批、关键临床阳性、BD或销售超预期），则可把单一资产失败概率分散；若只有1个核心资产支撑，则估值折价应提高。', true, 'valid', '当前基数：商业化销售30.331亿元；已获批产品及适应症纳入医保；目标节点数：未来12个月至少2个重大节点。估值假设：其他产品/管线风险调整价值基准300-450亿港元；若节点少于2个，下修至150-250亿港元。', '若未来12个月重大临床/注册/销售/BD节点少于2个，或其他管线风险调整价值下修到200亿港元以下，则该论点失效。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：管线组合不是定性“丰富”，必须用节点数量和风险调整估值约束；2个节点是维持平台估值的最低要求。', '快照：商业化销售30.331亿元；其他管线rNPV基准300-450亿港元；12个月节点阈值≥2个。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (74, 20, '情景收益：概率加权收益约19%，低于中际旭创，仓位应更谨慎', '按118.10港元入选价计算，熊市情景为依沃西进展不及预期、商业化销售仅38亿元，对应目标价约85港元，收益-28%；基准情景商业化45亿元、依沃西rNPV约700亿港元，对应目标价约145港元，收益+22.8%；牛市情景商业化60亿元、依沃西rNPV约950亿港元，对应目标价180港元，收益+52.4%。假设概率25%/45%/30%，概率加权目标价约140.5港元，期望收益约19.0%。', true, 'valid', '当前价118.10港元；目标价：熊85/基准145/牛180港元；概率：25%/45%/30%；概率加权目标价=85*25%+145*45%+180*30%=140.5港元；期望收益约19.0%。当前市值1087.87亿港元，牛市目标市值1658亿港元。', '若基准目标价下修到130港元以下，或熊市概率上升到40%以上，或概率加权期望收益低于15%，则该股不应维持active买入级状态。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：康方仍有50%牛市空间，但概率加权收益约19%，临床二元风险高，评分由85下调至82。', '快照：入选价118.10港元；熊/基准/牛85/145/180港元；概率加权收益19.0%；失效阈值期望收益15%。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (75, 21, '收入桥接：海外收入占比43.8%，2026E收入需达到520-650亿元才支撑目标价', '泡泡玛特不能只讲“全球化品牌”。2025收入371.2亿元，若2026E达到520-650亿元，对应同比增长约40%-75%；其中海外收入占比已达43.8%，即2025海外收入约162.6亿元。若海外继续增长50%，仅海外可新增约81亿元；国内和新品若新增约70-190亿元，则全年收入目标有路径。', true, 'valid', '当前基数：2025收入371.2亿元/+184.7%；海外占比43.8%，估算海外收入约162.6亿元。目标假设：2026E收入熊450亿元（+21%）、基准520亿元（+40%）、牛650亿元（+75%）。桥接：基准520亿元需新增148.8亿元；若海外+50%贡献约81.3亿元，剩余需国内/新品贡献约67.5亿元。', '若海外收入增速连续2个季度低于30%，或2026E收入预期低于500亿元，或渠道库存周转天数较上年增加超过30%，则该论点失效。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：全球化不是口号，海外收入162.6亿元基数和50%增长假设可解释基准收入520亿元路径。', '快照：2025收入371.2亿元；海外占比43.8%≈162.6亿元；2026E收入情景450/520/650亿元。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (76, 21, '利润桥接：目标估值要求2026E净利至少170亿元，净利率需维持28%-32%', '2025净利润约128-130亿元，若2026E净利170-210亿元，对应同比约31%-64%。这不是线性外推，而是收入增长、IP高毛利和规模效应共同作用。若收入520亿元、净利率32.7%，净利约170亿元；若收入650亿元、净利率32.3%，净利约210亿元。若净利率跌破28%，即便收入520亿元，净利仅约146亿元，目标价需要明显下修。', true, 'valid', '当前基数：2025净利润约128-130亿元；2025收入371.2亿元，估算净利率约34.5%-35.0%。目标假设：2026E净利熊145亿元、基准170亿元、牛210亿元；对应收入520亿元时净利率32.7%，收入650亿元时净利率32.3%。', '若净利率低于28%，或2026E净利预期下修至150亿元以下，或毛利率连续2个季度下滑超过5pct，则该论点失效。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：目标价265港元需要170-210亿元净利区间支撑；净利率28%是硬止损线。', '快照：2025净利128-130亿元；净利率约34.5%-35.0%；2026E净利情景145/170/210亿元；失效阈值150亿元/28%。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (77, 21, 'IP护城河量化：单一爆款风险必须用非单一IP占比、新品转化率和库存指标验证', '泡泡玛特最大风险是Labubu等爆款生命周期，因此护城河不能只说“IP矩阵”。量化验证应看：非单一IP收入占比是否维持在50%以上，新品首发售罄率是否保持高位，库存周转是否不恶化。若单一IP贡献过高且库存上升，利润会在1-2个季度内快速回落。', true, 'valid', '当前基数：2025收入371.2亿元、海外收入约162.6亿元、净利约128-130亿元。护城河目标指标：非最大IP收入占比≥50%；新品首发售罄率/补货转化保持高位；库存周转天数同比增加不超过30%；毛利率下滑不超过5pct。', '若最大单一IP收入占比超过50%且连续2个季度新品转化率下降，或库存周转天数同比增加超过30%，或毛利率下滑超过5pct，则该论点失效。', '2026-05-31', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', '2026-05-31 08:03:38.842982+08', 1, '本次量化复核认为：IP矩阵必须经得起数据检验；库存和非单一IP占比是防止利润突然下滑的关键指标。', '快照：收入371.2亿元；净利128-130亿元；海外约162.6亿元；护城河阈值：非单一IP≥50%、库存周转恶化≤30%、毛利率下滑≤5pct。', '2026-06-07 08:03:38.842982+08');
INSERT INTO public.stock_theses VALUES (86, 23, '现金流短期偏弱是主要约束', '2026Q1经营现金流净额5.11亿元，同比-64.04%，明显低于12.42亿元净利润，可能来自扩产、存货或应收增加。若高端PCB需求真实，后续交付回款应改善现金利润比；否则需降级为观察。', true, 'valid', '2026Q1经营现金流净额5.11亿元，同比-64.04%；归母净利润12.42亿元；现金利润比约41.1%；加权ROE 7.81%。', '若连续2个季度经营现金流/净利润低于35%，或应收账款增速高于收入增速20个百分点以上，或资产负债率升至55%以上，则财务质量论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, '现金流弱于利润，列为重点风险而非排除项。', '2026Q1经营现金流净额5.11亿元，同比-64.04%；归母净利润12.42亿元；现金利润比约41.1%；加权ROE 7.81%。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (87, 24, '产品收入高增验证商业化平台', '2026Q1产品收入超过38亿元、同比超过50%，较2025全年产品收入约118亿元的季度均值29.5亿元高约28.8%。若Q2-Q4维持40/43/46亿元，2026产品收入可达约167亿元，同比约42%，足以支撑创新药平台从研发折现转向收入利润兑现。', true, 'valid', '2026Q1产品收入>38亿元，同比>50%；2025产品收入约118亿元；2026基准产品收入测算约167亿元；Q1相对2025季度均值+28.8%。', '若任一季度产品收入低于34亿元，或连续2个季度产品收入同比增速低于30%，或2026全年产品收入预期下修至145亿元以下，则商业化平台论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, 'Q1产品收入继续高增，是本次入选的核心量化依据。', '2026Q1产品收入>38亿元，同比>50%；2025产品收入约118亿元；2026基准产品收入测算约167亿元；Q1相对2025季度均值+28.8%。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (88, 24, '玛仕度肽提供第二增长曲线', '玛仕度肽被市场预测2025年销售额约7亿元、2026年约18亿元、峰值约52亿元。若2026年达到18亿元，相当于2025产品收入118亿元的15.3%，并可在减重/代谢领域带来更高患者覆盖和自费属性，降低单一肿瘤产品依赖。', true, 'valid', '玛仕度肽2025E销售额约7亿元；2026E约18亿元；峰值销售预测约52亿元；2026E占2025产品收入118亿元的15.3%。', '若玛仕度肽2026H1销售额低于6亿元，或全年销售预期下修至12亿元以下，或关键渠道月新增处方连续2个月环比下降超过15%，则第二增长曲线论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, '玛仕度肽预期具备量化放量路径，但需跟踪实际处方和渠道。', '玛仕度肽2025E销售额约7亿元；2026E约18亿元；峰值销售预测约52亿元；2026E占2025产品收入118亿元的15.3%。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (89, 24, '肿瘤与综合产品线形成多产品放量组合', '公司公告指出五款TKI新增纳入医保后快速放量，2026年5月达伯舒联合爱优特获批晚期/转移性肾细胞癌适应症。多产品组合能平滑单品生命周期，若新增适应症带来季度增量2-3亿元，将提高产品收入稳定性。', true, 'valid', '五款TKI新增纳入NRDL；2026-05达伯舒+爱优特获批肾细胞癌适应症；2026Q1产品收入>38亿元；假设新增适应症季度增量2-3亿元。', '若医保新增品种合计季度增量低于1亿元，或新适应症获批后2个季度内未带来至少5%产品收入环比增量，或核心产品价格降幅超过25%，则组合放量论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, '多产品获批和医保放量增强了收入可持续性。', '五款TKI新增纳入NRDL；2026-05达伯舒+爱优特获批肾细胞癌适应症；2026Q1产品收入>38亿元；假设新增适应症季度增量2-3亿元。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (90, 24, '估值与机构目标价存在预期差', '当前股价约74.85港元；近期可见机构目标价包括野村114.64港元、中信建投137.51港元。采用118港元作为基准目标价，低于乐观目标但高于保守目标；对应较现价约57.7%空间，且由产品收入增速、玛仕度肽和多产品组合支撑。', true, 'valid', '当前股价74.85港元；野村目标价114.64港元；中信建投目标价137.51港元；本次基准目标价118港元；预期涨幅57.65%。', '若主流机构目标价中位数降至95港元以下，或股价跌破60港元且产品收入增速低于30%，或新药管线出现单项重大临床失败导致估值下修超过20%，则预期差论点失效。', '2026-06-01', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', '2026-06-01 08:04:54.231408+08', 1, '当前机构目标价与现价仍存在足够差距，但需由收入增速兑现。', '当前股价74.85港元；野村目标价114.64港元；中信建投目标价137.51港元；本次基准目标价118港元；预期涨幅57.65%。', '2026-06-08 08:04:54.231408+08');
INSERT INTO public.stock_theses VALUES (91, 25, 'AI PCB与光通信订单把消费电子周期股改造成算力链公司', '公司2026Q1营业收入131.38亿元、同比+52.72%，归母净利润11.10亿元、同比+143.47%，已经不是单纯消费电子代工逻辑。机构口径预计2026年AI PCB收入约200亿元，且Q2 AI PCB占比有望达到28%以上、环比Q1提升约35%，说明高端PCB订单在收入结构中的权重快速抬升。若全年收入按Q1 131.38亿元为底、后三季度分别提升至145/160/175亿元，全年收入约611亿元，AI PCB约200亿元将占约32.7%，足以改变利润率中枢。', true, 'valid', '2026Q1收入131.38亿元，同比+52.72%；2026Q1归母净利润11.10亿元，同比+143.47%；机构预计2026年AI PCB收入约200亿元；Q2 AI PCB占比28%+、环比Q1约+35%；基准测算2026全年收入约611亿元。', '若未来任一季度总收入低于120亿元，或AI PCB季度收入低于45亿元，或连续2个季度总收入同比增速低于30%，则“算力订单改造收入结构”论点失效。', '2026-06-02', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', 1, 'Q1收入和利润增速已验证算力链订单开始体现在报表，下一步重点看Q2 AI PCB占比能否达到28%+。', '2026Q1收入131.38亿元，同比+52.72%；2026Q1归母净利润11.10亿元，同比+143.47%；机构预计2026年AI PCB收入约200亿元；Q2 AI PCB占比28%+、环比Q1约+35%；基准测算2026全年收入约611亿元。', '2026-06-09 08:17:09.024271+08');
INSERT INTO public.stock_theses VALUES (92, 25, '利润上修有明确桥接路径而非单季线性外推', '截至2026-06-01，12家机构预测2026 EPS为3.67元、归母净利润67.18亿元、同比+384.69%；另有研报预测2026/2027/2028年归母净利润约68.78/128.24/192.67亿元。公司Q1已实现净利润11.10亿元，占2026一致预期约16.5%，后三季度需合计56.08亿元、季度均值18.69亿元，较Q1高约68.4%。这个爬坡要求较高，但GMD并表后Q2预计贡献1.0-1.5亿元净利润，叠加AI PCB交付占比提升，可形成从Q1到H2的利润桥接。', true, 'valid', '2026E EPS 3.67元；2026E归母净利润67.18亿元，同比+384.69%；2027E净利润约128.24亿元；Q1净利润11.10亿元，占2026E约16.5%；后三季度隐含季度均值18.69亿元；GMD Q2预计贡献1.0-1.5亿元净利润。', '若2026H1归母净利润低于28亿元，或2026E一致预期净利润下修至55亿元以下，或GMD并表后单季度净利润贡献低于0.8亿元，则利润上修论点失效。', '2026-06-02', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', 1, '利润上修路径可量化跟踪：H1至少28亿元、全年预期不低于55亿元是核心防线。', '2026E EPS 3.67元；2026E归母净利润67.18亿元，同比+384.69%；2027E净利润约128.24亿元；Q1净利润11.10亿元，占2026E约16.5%；后三季度隐含季度均值18.69亿元；GMD Q2预计贡献1.0-1.5亿元净利润。', '2026-06-09 08:17:09.024271+08');
INSERT INTO public.stock_theses VALUES (93, 25, '目标估值依赖2027年盈利兑现，估值扩张假设受控', '2026-06-01股价191.75元、总股本约18.32亿股、总市值3512.11亿元。以2027E净利润128.24亿元折算EPS约7.00元，给予约42.9倍PE，对应目标价300元、目标市值约5496亿元；该PE低于部分AI硬件高峰估值，但仍要求2027利润高兑现。情景测算：牛市360元(2027E约51倍PE，30%)，基准300元(42.9倍PE，50%)，熊市150元(2026E约40.9倍PE但预期下修，20%)，概率加权目标约286元，期望收益约49.2%。', true, 'valid', '当前价191.75元；当前总市值3512.11亿元；总股本约18.32亿股；2027E净利润128.24亿元、EPS约7.00元；目标价300元、目标市值约5496亿元；牛/基准/熊概率30%/50%/20%，加权收益约49.2%。', '若2027E净利润预期下修至95亿元以下，或市场给予AI PCB公司的2027E目标PE压缩至30倍以下，或股价跌破150元且盈利预期同步下修，则估值论点失效。', '2026-06-02', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', 1, '目标价不是独立论点，必须由2027净利润约128亿元和AI PCB收入占比提升共同支撑。', '当前价191.75元；当前总市值3512.11亿元；总股本约18.32亿股；2027E净利润128.24亿元、EPS约7.00元；目标价300元、目标市值约5496亿元；牛/基准/熊概率30%/50%/20%，加权收益约49.2%。', '2026-06-09 08:17:09.024271+08');
INSERT INTO public.stock_theses VALUES (94, 25, '现金流质量尚可但杠杆和商誉是硬约束', '2026Q1经营活动现金净流入11.27亿元，略高于11.10亿元归母净利润，现金利润比约101.5%，说明当季利润并非完全由应收或存货堆出来。但资产负债率63.69%、商誉47.69亿元且占净资产21.07%，显著高于低风险成长股，需要把现金流和减值风险作为持续跟踪项。只要经营现金流能够持续覆盖净利润、商誉不出现大额减值，较高杠杆尚可由收入高增长消化。', true, 'valid', '2026Q1经营现金流11.27亿元；2026Q1归母净利润11.10亿元；现金利润比约101.5%；资产负债率63.69%；商誉47.69亿元、占净资产21.07%；Q1毛利率19.33%、净利率8.56%。', '若连续2个季度经营现金流/净利润低于50%，或资产负债率升至68%以上，或年度商誉减值超过10亿元，或单季净利率跌破7%，则财务质量论点失效。', '2026-06-02', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', 1, 'Q1现金流匹配利润，但负债率和商誉决定仓位不能按低风险龙头处理。', '2026Q1经营现金流11.27亿元；2026Q1归母净利润11.10亿元；现金利润比约101.5%；资产负债率63.69%；商誉47.69亿元、占净资产21.07%；Q1毛利率19.33%、净利率8.56%。', '2026-06-09 08:17:09.024271+08');
INSERT INTO public.stock_theses VALUES (95, 26, 'AI服务器出货把收入增长从消费电子代工切换为算力基建', '2026Q1工业富联实现收入2510.78亿元、同比+56.52%，归母净利润105.95亿元、同比+102.55%。研报口径显示云计算业务收入同比翻倍，AI GPU服务器出货量同比增长3.8倍、ASIC服务器出货量同比增长3.2倍，说明收入增长来自算力产品结构升级而非低毛利传统代工扩张。若Q2-Q4收入分别达到2800/3100/3400亿元，全年收入约11811亿元，较2025年9028.87亿元约+30.8%，在万亿收入基数上仍具规模弹性。', true, 'valid', '2026Q1收入2510.78亿元，同比+56.52%；2026Q1归母净利润105.95亿元，同比+102.55%；云计算业务收入同比翻倍；AI GPU服务器出货量同比+3.8倍，ASIC服务器出货量同比+3.2倍；2025收入9028.87亿元；基准测算2026收入约11811亿元。', '若未来任一季度收入低于2400亿元，或AI GPU/ASIC服务器出货增速连续2个季度低于100%，或云计算业务收入增速降至50%以下，则收入切换论点失效。', '2026-06-02', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', 1, 'Q1收入高增长与AI服务器出货倍数相互印证，后续看Q2收入是否维持2400亿元以上。', '2026Q1收入2510.78亿元，同比+56.52%；2026Q1归母净利润105.95亿元，同比+102.55%；云计算业务收入同比翻倍；AI GPU服务器出货量同比+3.8倍，ASIC服务器出货量同比+3.2倍；2025收入9028.87亿元；基准测算2026收入约11811亿元。', '2026-06-09 08:17:09.024271+08');
INSERT INTO public.stock_theses VALUES (96, 26, '利润率提升来自产品结构而不只是规模扩大', '公司2026Q1净利润105.95亿元、扣非净利润102.50亿元，扣非同比+109.05%，高于收入56.52%的增速，表明AI服务器和高速网络产品占比提升正在推高利润弹性。2025全年净利润352.86亿元、同比+51.99%，2026年19家机构一致预测净利润615.15亿元、同比+74.33%，EPS 3.10元；Q1已完成全年预测约17.2%，后三季度需实现509.20亿元、季度均值169.73亿元，要求Q2-Q4明显爬坡，但与AI订单交付节奏匹配。', true, 'valid', '2025净利润352.86亿元，同比+51.99%；2026Q1净利润105.95亿元，同比+102.55%；2026Q1扣非净利润102.50亿元，同比+109.05%；19家机构预测2026净利润615.15亿元、同比+74.33%，EPS 3.10元；Q1完成全年预测17.2%。', '若2026H1归母净利润低于250亿元，或2026E一致预期净利润下修至520亿元以下，或单季扣非净利率低于3.8%，则利润率提升论点失效。', '2026-06-02', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', 1, '利润增速高于收入增速，核心验证点是H1净利润能否达到250亿元以上。', '2025净利润352.86亿元，同比+51.99%；2026Q1净利润105.95亿元，同比+102.55%；2026Q1扣非净利润102.50亿元，同比+109.05%；19家机构预测2026净利润615.15亿元、同比+74.33%，EPS 3.10元；Q1完成全年预测17.2%。', '2026-06-09 08:17:09.024271+08');
INSERT INTO public.stock_theses VALUES (97, 26, '现金流验证AI订单真实且降低大市值公司的回撤风险', '2026Q1经营活动现金净流入250.24亿元，同比增长1826.20%，为当季归母净利润105.95亿元的2.36倍，显示订单回款和供应链占款能力强。毛利率7.35%虽仍是制造业低毛利模式，但较产品结构优化前改善；资产负债率61.38%处于可接受但需跟踪区间。对大市值公司而言，现金流强于利润能显著降低因应收和库存恶化导致的业绩失真风险。', true, 'valid', '2026Q1经营现金流250.24亿元，同比+1826.20%；2026Q1归母净利润105.95亿元；经营现金流/净利润约236%；2026Q1毛利率7.35%；资产负债率61.38%；基本EPS 0.53元，同比+103.85%。', '若连续2个季度经营现金流/净利润低于80%，或资产负债率升至68%以上，或单季毛利率跌破6.5%，则现金流质量论点失效。', '2026-06-02', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', 1, 'Q1现金流远超净利润，是本次入选区别于纯题材算力股的重要量化支撑。', '2026Q1经营现金流250.24亿元，同比+1826.20%；2026Q1归母净利润105.95亿元；经营现金流/净利润约236%；2026Q1毛利率7.35%；资产负债率61.38%；基本EPS 0.53元，同比+103.85%。', '2026-06-09 08:17:09.024271+08');
INSERT INTO public.stock_theses VALUES (98, 26, '估值预期差来自Forward PE而非追逐最高目标价', '2026-06-01附近现价约73.75元，富途口径目标价平均约73.39元、最高94.44元，说明卖方平均目标价并未给出50%空间；本次入选的预期差在于市场尚未把2026E净利润615.15亿元完全按AI硬件龙头定价。以2026E EPS 3.10元、目标PE 38.7倍得到120元目标价，Forward PEG约0.52；情景为牛135元(25%)、基准120元(45%)、熊60元(30%)，概率加权目标105.75元，期望收益约43.4%。若后续Q2 EPS预期继续上修，目标价具备被动上修可能。', true, 'valid', '现价约73.75元；机构目标价平均73.39元、最高94.44元；2026E EPS 3.10元；2026E净利润615.15亿元、同比+74.33%；目标PE 38.7倍；目标价120元；牛/基准/熊概率25%/45%/30%，加权收益约43.4%。', '若2026E EPS下修至2.60元以下，或市场给予AI服务器制造环节的合理PE降至28倍以下，或Q2发布前机构最高目标价仍低于100元且盈利预期无上修，则估值预期差论点失效。', '2026-06-02', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', '2026-06-02 08:17:09.024271+08', 1, '目标价依赖盈利上修与Forward PE重估，不依赖单纯“AI热门”叙事；若Q2无上修需降级复核。', '现价约73.75元；机构目标价平均73.39元、最高94.44元；2026E EPS 3.10元；2026E净利润615.15亿元、同比+74.33%；目标PE 38.7倍；目标价120元；牛/基准/熊概率25%/45%/30%，加权收益约43.4%。', '2026-06-09 08:17:09.024271+08');


--
-- Name: rule_versions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.rule_versions_id_seq', 8, true);


--
-- Name: stock_pick_reviews_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.stock_pick_reviews_id_seq', 8, true);


--
-- Name: stock_picks_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.stock_picks_id_seq', 26, true);


--
-- Name: stock_theses_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.stock_theses_id_seq', 98, true);


--
-- Name: rule_versions rule_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rule_versions
    ADD CONSTRAINT rule_versions_pkey PRIMARY KEY (id);


--
-- Name: rule_versions rule_versions_version_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rule_versions
    ADD CONSTRAINT rule_versions_version_key UNIQUE (version);


--
-- Name: stock_pick_reviews stock_pick_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_pick_reviews
    ADD CONSTRAINT stock_pick_reviews_pkey PRIMARY KEY (id);


--
-- Name: stock_picks stock_picks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_picks
    ADD CONSTRAINT stock_picks_pkey PRIMARY KEY (id);


--
-- Name: stock_picks stock_picks_stock_code_selected_date_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_picks
    ADD CONSTRAINT stock_picks_stock_code_selected_date_key UNIQUE (stock_code, selected_date);


--
-- Name: stock_theses stock_theses_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_theses
    ADD CONSTRAINT stock_theses_pkey PRIMARY KEY (id);


--
-- Name: idx_stock_pick_reviews_pick_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_stock_pick_reviews_pick_id ON public.stock_pick_reviews USING btree (stock_pick_id);


--
-- Name: idx_stock_picks_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_stock_picks_code ON public.stock_picks USING btree (stock_code);


--
-- Name: idx_stock_picks_selected_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_stock_picks_selected_date ON public.stock_picks USING btree (selected_date DESC);


--
-- Name: idx_stock_picks_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_stock_picks_status ON public.stock_picks USING btree (status);


--
-- Name: idx_stock_theses_pick_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_stock_theses_pick_id ON public.stock_theses USING btree (stock_pick_id);


--
-- Name: idx_stock_theses_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_stock_theses_status ON public.stock_theses USING btree (status);


--
-- Name: idx_stock_theses_validity_last_checked_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_stock_theses_validity_last_checked_at ON public.stock_theses USING btree (validity_last_checked_at);


--
-- Name: ux_stock_picks_one_open_per_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ux_stock_picks_one_open_per_code ON public.stock_picks USING btree (stock_code) WHERE ((status)::text = ANY ((ARRAY['active'::character varying, 'watching'::character varying])::text[]));


--
-- Name: stale_stock_picks_for_thesis_review _RETURN; Type: RULE; Schema: public; Owner: postgres
--

CREATE OR REPLACE VIEW public.stale_stock_picks_for_thesis_review AS
 SELECT sp.id AS stock_pick_id,
    sp.stock_code,
    sp.stock_name,
    sp.market,
    sp.selected_date,
    sp.selected_price,
    sp.sector,
    sp.expected_upside_pct,
    sp.status AS stock_status,
    count(st.id) AS thesis_count,
    min(st.validity_last_checked_at) AS oldest_thesis_validity_checked_at,
    max(st.validity_last_checked_at) AS newest_thesis_validity_checked_at,
    count(*) FILTER (WHERE ((st.validity_last_checked_at IS NULL) OR (st.validity_last_checked_at < (now() - '7 days'::interval)))) AS stale_thesis_count
   FROM (public.stock_picks sp
     JOIN public.stock_theses st ON ((st.stock_pick_id = sp.id)))
  WHERE ((sp.status)::text = ANY ((ARRAY['active'::character varying, 'watching'::character varying])::text[]))
  GROUP BY sp.id
 HAVING (count(*) FILTER (WHERE ((st.validity_last_checked_at IS NULL) OR (st.validity_last_checked_at < (now() - '7 days'::interval)))) > 0)
  ORDER BY (min(st.validity_last_checked_at)) NULLS FIRST, sp.selected_date, sp.id;


--
-- Name: stock_picks trg_stock_picks_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_stock_picks_updated_at BEFORE UPDATE ON public.stock_picks FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: stock_theses trg_stock_theses_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_stock_theses_updated_at BEFORE UPDATE ON public.stock_theses FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: stock_pick_reviews stock_pick_reviews_stock_pick_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_pick_reviews
    ADD CONSTRAINT stock_pick_reviews_stock_pick_id_fkey FOREIGN KEY (stock_pick_id) REFERENCES public.stock_picks(id) ON DELETE CASCADE;


--
-- Name: stock_theses stock_theses_stock_pick_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_theses
    ADD CONSTRAINT stock_theses_stock_pick_id_fkey FOREIGN KEY (stock_pick_id) REFERENCES public.stock_picks(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict cv7R3htcNtcesxBY57E9aLh2StNySckv2mxF9ywzJepbN65JFevOix8aZj2NiwX

