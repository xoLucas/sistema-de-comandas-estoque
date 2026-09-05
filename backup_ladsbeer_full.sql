--
-- PostgreSQL database dump
--

\restrict IPi4cBqgaZ4g7eRYdbvdIoMKVknma5UciJ4phfJJG225rYVAqRrPd51xqP2wvg8

-- Dumped from database version 17.10
-- Dumped by pg_dump version 17.10

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: cash_position_movements; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.cash_position_movements (
    id integer NOT NULL,
    type character varying(20) NOT NULL,
    source character varying(20) NOT NULL,
    title character varying(120) NOT NULL,
    amount double precision NOT NULL,
    observation character varying(255),
    session_id integer,
    created_by_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.cash_position_movements OWNER TO postgres;

--
-- Name: cash_position_movements_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.cash_position_movements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.cash_position_movements_id_seq OWNER TO postgres;

--
-- Name: cash_position_movements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.cash_position_movements_id_seq OWNED BY public.cash_position_movements.id;


--
-- Name: cash_register_movements; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.cash_register_movements (
    id integer NOT NULL,
    session_id integer NOT NULL,
    type character varying(20) NOT NULL,
    amount double precision NOT NULL,
    note text,
    created_by_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.cash_register_movements OWNER TO postgres;

--
-- Name: cash_register_movements_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.cash_register_movements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.cash_register_movements_id_seq OWNER TO postgres;

--
-- Name: cash_register_movements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.cash_register_movements_id_seq OWNED BY public.cash_register_movements.id;


--
-- Name: cash_register_sessions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.cash_register_sessions (
    id integer NOT NULL,
    opened_at timestamp with time zone DEFAULT now() NOT NULL,
    closed_at timestamp with time zone,
    opened_by_id integer NOT NULL,
    closed_by_id integer,
    initial_cash double precision NOT NULL,
    final_cash double precision,
    status character varying(20) NOT NULL,
    observations text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.cash_register_sessions OWNER TO postgres;

--
-- Name: cash_register_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.cash_register_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.cash_register_sessions_id_seq OWNER TO postgres;

--
-- Name: cash_register_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.cash_register_sessions_id_seq OWNED BY public.cash_register_sessions.id;


--
-- Name: categories; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.categories (
    id integer NOT NULL,
    name character varying(50) NOT NULL,
    printer character varying(20),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.categories OWNER TO postgres;

--
-- Name: categories_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.categories_id_seq OWNER TO postgres;

--
-- Name: categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.categories_id_seq OWNED BY public.categories.id;


--
-- Name: consignment_order_items; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.consignment_order_items (
    id integer NOT NULL,
    consignment_order_id integer NOT NULL,
    product_id integer NOT NULL,
    quantity integer NOT NULL,
    unit_price double precision NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.consignment_order_items OWNER TO postgres;

--
-- Name: consignment_order_items_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.consignment_order_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.consignment_order_items_id_seq OWNER TO postgres;

--
-- Name: consignment_order_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.consignment_order_items_id_seq OWNED BY public.consignment_order_items.id;


--
-- Name: consignment_orders; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.consignment_orders (
    id integer NOT NULL,
    customer_id integer NOT NULL,
    source_order_id integer,
    waiter_id integer,
    order_type character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    total double precision NOT NULL,
    amount_paid double precision NOT NULL,
    balance double precision NOT NULL,
    due_date date,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    closed_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.consignment_orders OWNER TO postgres;

--
-- Name: consignment_orders_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.consignment_orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.consignment_orders_id_seq OWNER TO postgres;

--
-- Name: consignment_orders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.consignment_orders_id_seq OWNED BY public.consignment_orders.id;


--
-- Name: consignment_payments; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.consignment_payments (
    id integer NOT NULL,
    consignment_order_id integer NOT NULL,
    user_id integer,
    amount double precision NOT NULL,
    service_portion double precision NOT NULL,
    payment_method character varying(30),
    card_machine character varying(30),
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.consignment_payments OWNER TO postgres;

--
-- Name: consignment_payments_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.consignment_payments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.consignment_payments_id_seq OWNER TO postgres;

--
-- Name: consignment_payments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.consignment_payments_id_seq OWNED BY public.consignment_payments.id;


--
-- Name: customers; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.customers (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    phone character varying(50),
    email character varying(100),
    document character varying(30),
    birth_date date,
    customer_type character varying(20) NOT NULL,
    notes text,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.customers OWNER TO postgres;

--
-- Name: customers_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.customers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.customers_id_seq OWNER TO postgres;

--
-- Name: customers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.customers_id_seq OWNED BY public.customers.id;


--
-- Name: daily_payments; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.daily_payments (
    id integer NOT NULL,
    employee_id integer NOT NULL,
    amount double precision NOT NULL,
    payment_date timestamp with time zone NOT NULL,
    notes text,
    registered_by_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.daily_payments OWNER TO postgres;

--
-- Name: daily_payments_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.daily_payments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.daily_payments_id_seq OWNER TO postgres;

--
-- Name: daily_payments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.daily_payments_id_seq OWNED BY public.daily_payments.id;


--
-- Name: employees; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.employees (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    age integer,
    nickname character varying(50),
    contact character varying(100),
    role character varying(50) NOT NULL,
    user_id integer,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.employees OWNER TO postgres;

--
-- Name: employees_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.employees_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.employees_id_seq OWNER TO postgres;

--
-- Name: employees_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.employees_id_seq OWNED BY public.employees.id;


--
-- Name: expenses; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.expenses (
    id integer NOT NULL,
    description character varying(255) NOT NULL,
    amount double precision NOT NULL,
    category character varying(50) NOT NULL,
    expense_date timestamp with time zone NOT NULL,
    reference_id integer,
    reference_type character varying(50),
    created_by_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.expenses OWNER TO postgres;

--
-- Name: expenses_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.expenses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.expenses_id_seq OWNER TO postgres;

--
-- Name: expenses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.expenses_id_seq OWNED BY public.expenses.id;


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.notifications (
    id integer NOT NULL,
    type character varying(50) NOT NULL,
    title character varying(255) NOT NULL,
    message character varying(500) NOT NULL,
    details json,
    status character varying(20) NOT NULL,
    resolution character varying(20),
    resolved_by_id integer,
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.notifications OWNER TO postgres;

--
-- Name: notifications_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.notifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.notifications_id_seq OWNER TO postgres;

--
-- Name: notifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.notifications_id_seq OWNED BY public.notifications.id;


--
-- Name: order_items; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.order_items (
    id integer NOT NULL,
    order_id integer NOT NULL,
    order_round_id integer,
    product_id integer NOT NULL,
    quantity integer NOT NULL,
    unit_price double precision NOT NULL,
    unit_cost double precision,
    is_pending boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.order_items OWNER TO postgres;

--
-- Name: order_items_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.order_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.order_items_id_seq OWNER TO postgres;

--
-- Name: order_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.order_items_id_seq OWNED BY public.order_items.id;


--
-- Name: order_rounds; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.order_rounds (
    id integer NOT NULL,
    order_id integer NOT NULL,
    round_number integer NOT NULL,
    observation character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.order_rounds OWNER TO postgres;

--
-- Name: order_rounds_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.order_rounds_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.order_rounds_id_seq OWNER TO postgres;

--
-- Name: order_rounds_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.order_rounds_id_seq OWNED BY public.order_rounds.id;


--
-- Name: orders; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.orders (
    id integer NOT NULL,
    table_id integer NOT NULL,
    waiter_id integer,
    closed_by_id integer,
    closed_waiter_id integer,
    customer_id integer,
    customer_name character varying(100),
    status character varying(20) NOT NULL,
    total double precision NOT NULL,
    partial_payment double precision NOT NULL,
    partial_service_charge double precision NOT NULL,
    partial_payments_detail json,
    service_charge_pct double precision NOT NULL,
    service_charge_applied boolean NOT NULL,
    service_charge_amount double precision NOT NULL,
    payment_method character varying(30),
    card_machine character varying(30),
    is_estorno boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    closed_at timestamp with time zone
);


ALTER TABLE public.orders OWNER TO postgres;

--
-- Name: orders_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.orders_id_seq OWNER TO postgres;

--
-- Name: orders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.orders_id_seq OWNED BY public.orders.id;


--
-- Name: products; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.products (
    id integer NOT NULL,
    code character varying(50),
    name character varying(100) NOT NULL,
    category character varying(50) NOT NULL,
    cost double precision NOT NULL,
    margin_pct double precision NOT NULL,
    price double precision NOT NULL,
    stock integer NOT NULL,
    min_stock integer NOT NULL,
    printer character varying(20),
    active boolean NOT NULL,
    pack_unit_product_id integer,
    pack_size integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.products OWNER TO postgres;

--
-- Name: products_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.products_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.products_id_seq OWNER TO postgres;

--
-- Name: products_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.products_id_seq OWNED BY public.products.id;


--
-- Name: promotion_product; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.promotion_product (
    promotion_id integer NOT NULL,
    product_id integer NOT NULL
);


ALTER TABLE public.promotion_product OWNER TO postgres;

--
-- Name: promotions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.promotions (
    id integer NOT NULL,
    name character varying(150) NOT NULL,
    description character varying(255),
    discount_pct double precision NOT NULL,
    start_at timestamp with time zone,
    end_at timestamp with time zone,
    is_active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.promotions OWNER TO postgres;

--
-- Name: promotions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.promotions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.promotions_id_seq OWNER TO postgres;

--
-- Name: promotions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.promotions_id_seq OWNED BY public.promotions.id;


--
-- Name: settings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.settings (
    id integer NOT NULL,
    key character varying(100) NOT NULL,
    value text,
    label character varying(100) NOT NULL,
    description text,
    type character varying(20) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.settings OWNER TO postgres;

--
-- Name: settings_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.settings_id_seq OWNER TO postgres;

--
-- Name: settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.settings_id_seq OWNED BY public.settings.id;


--
-- Name: stock_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.stock_history (
    id integer NOT NULL,
    product_id integer NOT NULL,
    order_id integer,
    consignment_order_id integer,
    table_id integer,
    type character varying(20) NOT NULL,
    quantity integer NOT NULL,
    note character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.stock_history OWNER TO postgres;

--
-- Name: stock_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.stock_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.stock_history_id_seq OWNER TO postgres;

--
-- Name: stock_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.stock_history_id_seq OWNED BY public.stock_history.id;


--
-- Name: supplier_product; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.supplier_product (
    supplier_id integer NOT NULL,
    product_id integer NOT NULL
);


ALTER TABLE public.supplier_product OWNER TO postgres;

--
-- Name: suppliers; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.suppliers (
    id integer NOT NULL,
    name character varying(150) NOT NULL,
    contact character varying(255),
    active boolean NOT NULL
);


ALTER TABLE public.suppliers OWNER TO postgres;

--
-- Name: suppliers_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.suppliers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.suppliers_id_seq OWNER TO postgres;

--
-- Name: suppliers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.suppliers_id_seq OWNED BY public.suppliers.id;


--
-- Name: tables; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tables (
    id integer NOT NULL,
    number integer NOT NULL,
    name character varying(100),
    status character varying(20) NOT NULL,
    is_balcao boolean NOT NULL,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.tables OWNER TO postgres;

--
-- Name: tables_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tables_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tables_id_seq OWNER TO postgres;

--
-- Name: tables_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tables_id_seq OWNED BY public.tables.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users (
    id integer NOT NULL,
    username character varying(50) NOT NULL,
    password_hash character varying(255) NOT NULL,
    name character varying(100) NOT NULL,
    role character varying(20) NOT NULL,
    is_registered boolean NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.users OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: cash_position_movements id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_position_movements ALTER COLUMN id SET DEFAULT nextval('public.cash_position_movements_id_seq'::regclass);


--
-- Name: cash_register_movements id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_register_movements ALTER COLUMN id SET DEFAULT nextval('public.cash_register_movements_id_seq'::regclass);


--
-- Name: cash_register_sessions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_register_sessions ALTER COLUMN id SET DEFAULT nextval('public.cash_register_sessions_id_seq'::regclass);


--
-- Name: categories id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.categories ALTER COLUMN id SET DEFAULT nextval('public.categories_id_seq'::regclass);


--
-- Name: consignment_order_items id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_order_items ALTER COLUMN id SET DEFAULT nextval('public.consignment_order_items_id_seq'::regclass);


--
-- Name: consignment_orders id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_orders ALTER COLUMN id SET DEFAULT nextval('public.consignment_orders_id_seq'::regclass);


--
-- Name: consignment_payments id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_payments ALTER COLUMN id SET DEFAULT nextval('public.consignment_payments_id_seq'::regclass);


--
-- Name: customers id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.customers ALTER COLUMN id SET DEFAULT nextval('public.customers_id_seq'::regclass);


--
-- Name: daily_payments id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_payments ALTER COLUMN id SET DEFAULT nextval('public.daily_payments_id_seq'::regclass);


--
-- Name: employees id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.employees ALTER COLUMN id SET DEFAULT nextval('public.employees_id_seq'::regclass);


--
-- Name: expenses id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.expenses ALTER COLUMN id SET DEFAULT nextval('public.expenses_id_seq'::regclass);


--
-- Name: notifications id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notifications ALTER COLUMN id SET DEFAULT nextval('public.notifications_id_seq'::regclass);


--
-- Name: order_items id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.order_items ALTER COLUMN id SET DEFAULT nextval('public.order_items_id_seq'::regclass);


--
-- Name: order_rounds id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.order_rounds ALTER COLUMN id SET DEFAULT nextval('public.order_rounds_id_seq'::regclass);


--
-- Name: orders id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.orders ALTER COLUMN id SET DEFAULT nextval('public.orders_id_seq'::regclass);


--
-- Name: products id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.products ALTER COLUMN id SET DEFAULT nextval('public.products_id_seq'::regclass);


--
-- Name: promotions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.promotions ALTER COLUMN id SET DEFAULT nextval('public.promotions_id_seq'::regclass);


--
-- Name: settings id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.settings ALTER COLUMN id SET DEFAULT nextval('public.settings_id_seq'::regclass);


--
-- Name: stock_history id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_history ALTER COLUMN id SET DEFAULT nextval('public.stock_history_id_seq'::regclass);


--
-- Name: suppliers id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.suppliers ALTER COLUMN id SET DEFAULT nextval('public.suppliers_id_seq'::regclass);


--
-- Name: tables id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tables ALTER COLUMN id SET DEFAULT nextval('public.tables_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Data for Name: cash_position_movements; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.cash_position_movements (id, type, source, title, amount, observation, session_id, created_by_id, created_at) FROM stdin;
\.


--
-- Data for Name: cash_register_movements; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.cash_register_movements (id, session_id, type, amount, note, created_by_id, created_at) FROM stdin;
\.


--
-- Data for Name: cash_register_sessions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.cash_register_sessions (id, opened_at, closed_at, opened_by_id, closed_by_id, initial_cash, final_cash, status, observations, created_at, updated_at) FROM stdin;
1	2026-09-05 13:14:35.363808-03	\N	2	\N	0	\N	open	\N	2026-09-05 13:14:35.363808-03	2026-09-05 13:14:35.363808-03
\.


--
-- Data for Name: categories; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.categories (id, name, printer, created_at) FROM stdin;
1	Copão e Doses	bar	2026-09-05 13:13:46.017236-03
2	Cervejas Latas	bar	2026-09-05 13:13:46.017236-03
3	Cervejas Garrafas 600ml	bar	2026-09-05 13:13:46.017236-03
4	Engradados	bar	2026-09-05 13:13:46.017236-03
5	Gin, Vodkas, Rum e Bitter	bar	2026-09-05 13:13:46.017236-03
6	Salgadinhos	cozinha	2026-09-05 13:13:46.017236-03
7	Água, Refrigerantes e Energéticos	bar	2026-09-05 13:13:46.017236-03
8	Cervejas Litrinho 300ml	bar	2026-09-05 13:13:46.017236-03
9	Whiskies	bar	2026-09-05 13:13:46.017236-03
10	Carvão e Gelo	bar	2026-09-05 13:13:46.017236-03
11	Cervejas Longnecks	bar	2026-09-05 13:13:46.017236-03
12	Espetinhos	cozinha	2026-09-05 13:13:46.017236-03
\.


--
-- Data for Name: consignment_order_items; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.consignment_order_items (id, consignment_order_id, product_id, quantity, unit_price, created_at, updated_at) FROM stdin;
1	1	42	1	200	2026-09-05 13:18:56.83181-03	2026-09-05 13:18:56.83181-03
2	2	42	1	200	2026-09-05 13:28:11.660898-03	2026-09-05 13:28:11.660898-03
\.


--
-- Data for Name: consignment_orders; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.consignment_orders (id, customer_id, source_order_id, waiter_id, order_type, status, total, amount_paid, balance, due_date, notes, created_at, closed_at, updated_at) FROM stdin;
2	2	2	2	pf	pago	220	220	0	\N	Gerado da comanda da mesa Mesa 10	2026-09-05 13:28:11.660898-03	2026-09-05 13:56:41.173538-03	2026-09-05 13:56:41.161587-03
1	1	1	2	pf	pago	220	220	0	\N	Gerado da comanda da mesa Mesa 10	2026-09-05 13:18:56.83181-03	2026-09-05 13:56:46.480956-03	2026-09-05 13:56:46.4769-03
\.


--
-- Data for Name: consignment_payments; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.consignment_payments (id, consignment_order_id, user_id, amount, service_portion, payment_method, card_machine, notes, created_at, updated_at) FROM stdin;
1	1	2	110	10	pix	\N	Pagamento parcial da comanda #1	2026-09-05 13:17:57.587668-03	2026-09-05 13:18:56.83181-03
2	2	2	110	10	pix	\N	Pagamento parcial da comanda #2	2026-09-05 13:23:23.281381-03	2026-09-05 13:28:11.660898-03
3	2	2	120	0	pix	1	\N	2026-09-05 13:56:41.161587-03	2026-09-05 13:56:41.161587-03
4	1	2	120	0	pix	1	\N	2026-09-05 13:56:46.4769-03	2026-09-05 13:56:46.4769-03
\.


--
-- Data for Name: customers; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.customers (id, name, phone, email, document, birth_date, customer_type, notes, active, created_at, updated_at) FROM stdin;
1	Lucas Dousseau	(27) 99827-8664	lucasdousseau@gmail.com	\N	\N	pf	\N	t	2026-09-05 13:17:36.800221-03	2026-09-05 13:17:36.800221-03
2	RAFAELA VIEIRA DOS SANTOS LTDA	(11) 11111-1111	\N	\N	\N	pf	\N	t	2026-09-05 13:28:10.012447-03	2026-09-05 13:28:10.012447-03
\.


--
-- Data for Name: daily_payments; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.daily_payments (id, employee_id, amount, payment_date, notes, registered_by_id, created_at) FROM stdin;
\.


--
-- Data for Name: employees; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.employees (id, name, age, nickname, contact, role, user_id, active, created_at, updated_at) FROM stdin;
1	teste1	\N	\N	\N	Garçom	\N	t	2026-09-05 13:18:26.774754-03	2026-09-05 13:18:26.774754-03
2	teste2	\N	\N	\N	Garçom	\N	t	2026-09-05 13:23:08.476914-03	2026-09-05 13:23:08.476914-03
\.


--
-- Data for Name: expenses; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.expenses (id, description, amount, category, expense_date, reference_id, reference_type, created_by_id, created_at) FROM stdin;
\.


--
-- Data for Name: notifications; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.notifications (id, type, title, message, details, status, resolution, resolved_by_id, resolved_at, created_at) FROM stdin;
1	stock_out	Produto em falta	CIROC está em falta (estoque: 2, mínimo: 1).	{"product_id": 42, "product_name": "CIROC", "status": "em_falta", "stock": 2, "min_stock": 1}	unread	\N	\N	\N	2026-09-05 13:17:42.323804-03
2	printer_failure	Falha na impressora do bar	Mesa 10 — pedido #1 — impressora Impressora Bar	{"function": "bar", "failed_printer_id": "2", "failed_printer_name": "Impressora Bar", "error": "[Errno 113] No route to host", "order_id": 1, "table_id": 10, "table_number": 10, "table_label": "Mesa 10", "round_number": 1, "items": [{"name": "CIROC", "quantity": 1}], "customer_name": "Lucas Dousseau", "waiter_name": "Gerente", "observation": null, "ficha_mode": false}	unread	\N	\N	\N	2026-09-05 13:17:49.821219-03
3	printer_failure	Falha na impressora do bar	Mesa 10 — pedido #1 — impressora Impressora Bar	{"function": "bar", "failed_printer_id": "2", "failed_printer_name": "Impressora Bar", "error": "[Errno 113] No route to host", "order_id": 2, "table_id": 10, "table_number": 10, "table_label": "Mesa 10", "round_number": 1, "items": [{"name": "CIROC", "quantity": 1}], "customer_name": null, "waiter_name": "Gerente", "observation": null, "ficha_mode": false}	unread	\N	\N	\N	2026-09-05 13:23:04.291391-03
\.


--
-- Data for Name: order_items; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.order_items (id, order_id, order_round_id, product_id, quantity, unit_price, unit_cost, is_pending, created_at) FROM stdin;
1	1	1	42	1	200	130	f	2026-09-05 13:17:42.323804-03
2	2	2	42	1	200	130	f	2026-09-05 13:22:56.140472-03
\.


--
-- Data for Name: order_rounds; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.order_rounds (id, order_id, round_number, observation, created_at) FROM stdin;
1	1	1	\N	2026-09-05 13:17:43.531576-03
2	2	1	\N	2026-09-05 13:22:57.894208-03
\.


--
-- Data for Name: orders; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.orders (id, table_id, waiter_id, closed_by_id, closed_waiter_id, customer_id, customer_name, status, total, partial_payment, partial_service_charge, partial_payments_detail, service_charge_pct, service_charge_applied, service_charge_amount, payment_method, card_machine, is_estorno, created_at, closed_at) FROM stdin;
1	10	2	2	\N	1	Lucas Dousseau	finalizada	200	100	10	[{"amount": 110.0, "product_portion": 100.0, "service_portion": 10.0, "method": "pix", "card_machine": null, "apply_service_charge": true, "created_at": "2026-09-05T16:17:57.587668+00:00"}]	0	f	10	fiado	\N	f	2026-09-05 13:17:37.556362-03	2026-09-05 13:18:56.863982-03
2	10	2	2	\N	\N	\N	finalizada	200	100	10	[{"amount": 110.0, "product_portion": 100.0, "service_portion": 10.0, "method": "pix", "card_machine": null, "apply_service_charge": true, "created_at": "2026-09-05T16:23:23.281381+00:00"}]	0	f	10	fiado	\N	f	2026-09-05 13:22:50.505282-03	2026-09-05 13:28:11.677136-03
\.


--
-- Data for Name: products; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.products (id, code, name, category, cost, margin_pct, price, stock, min_stock, printer, active, pack_unit_product_id, pack_size, created_at, updated_at) FROM stdin;
1	\N	AMSTEL GF 600ML RETORNAVEL	Cervejas Garrafas 600ml	6	0	10	144	48	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
2	\N	HEINEKEN GF 600ML RETORNAVEL	Cervejas Garrafas 600ml	8.8	0	14	192	48	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
3	\N	ORIGINAL GF 600ML RETORNAVEL	Cervejas Garrafas 600ml	7.5	0	12	144	48	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
4	\N	SPATEN GF 600ML RETORNAVEL	Cervejas Garrafas 600ml	7.5	0	12	120	48	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
5	\N	STELLA ARTOIS GF 600ML RETONAVEL	Cervejas Garrafas 600ml	8.2	0	13	72	24	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
6	\N	AMSTEL LT 473ML	Cervejas Latas	4.2	0	7	120	36	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
7	\N	BRAHMA CHOPP LT 473ML	Cervejas Latas	4.2	0	7	120	36	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
8	\N	BRAHMA DM LT 350ML	Cervejas Latas	3.5	0	6	120	36	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
9	\N	BUDWEISER LT 473ML	Cervejas Latas	4.2	0	7	120	36	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
10	\N	CORONA LT 473ML	Cervejas Latas	6.5	0	10	72	24	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
11	\N	HEINEKEN LT 473ML	Cervejas Latas	5	0	8	144	48	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
12	\N	LAGUNITAS LT 350ML	Cervejas Latas	6.5	0	10	48	12	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
13	\N	ORIGINAL LT 473ML	Cervejas Latas	4.2	0	7	120	36	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
14	\N	SPATEN LT 473ML	Cervejas Latas	4.2	0	7	120	36	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
15	\N	BUDWEISER LN 330ML	Cervejas Longnecks	5.5	0	9	72	24	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
16	\N	CORONA LN 330ML	Cervejas Longnecks	6	0	10	72	24	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
17	\N	CORONA CERO LN 330ML	Cervejas Longnecks	6	0	10	36	12	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
18	\N	HEINEKEN LN 330ML	Cervejas Longnecks	6	0	10	96	24	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
19	\N	SKOL BEATS SENSES/GT LONGNECK	Cervejas Longnecks	7	0	12	48	12	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
20	\N	STELLA ARTOIS PURE GOLD LN 330ML	Cervejas Longnecks	6	0	10	48	12	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
21	\N	WEMIX SABORES	Cervejas Longnecks	5.5	0	10	48	12	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
22	\N	BRAHMA CHOPP LITRINHO 300ML	Cervejas Litrinho 300ml	2.8	0	5	92	23	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
23	\N	ORIGINAL LITRINHO 300ML	Cervejas Litrinho 300ml	2.8	0	5	92	23	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
24	\N	CAVALO BRANCO 1L	Whiskies	65	0	110	8	2	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
25	\N	RED LABEL 1L	Whiskies	75	0	120	10	3	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
26	\N	BLACK LABEL 1L	Whiskies	115	0	180	5	2	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
27	\N	JACK DANIELS N07	Whiskies	130	0	200	6	2	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
28	\N	JACK DANIELS APPLE	Whiskies	130	0	200	6	2	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
29	\N	JACK DANIELS HONEY	Whiskies	130	0	200	4	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
30	\N	JACK DANIELS FIRE	Whiskies	130	0	200	3	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
31	\N	JACK DANIELS GENTLEMAN	Whiskies	180	0	280	3	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
32	\N	JACK DANIELS SELECT BARREL	Whiskies	220	0	340	2	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
33	\N	OLD PAR	Whiskies	150	0	240	4	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
34	\N	BALLANTINES	Whiskies	65	0	110	6	2	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
35	\N	BUFFALO TRACE	Whiskies	150	0	240	2	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
36	\N	BUCHANANS	Whiskies	160	0	260	3	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
37	\N	BOMBAY SAPHIRE	Gin, Vodkas, Rum e Bitter	90	0	140	4	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
38	\N	BEEFEATER LONDON	Gin, Vodkas, Rum e Bitter	75	0	120	5	2	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
39	\N	TANQUERAY LONDON	Gin, Vodkas, Rum e Bitter	90	0	140	6	2	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
40	\N	ABSOLUT RASPBERRY	Gin, Vodkas, Rum e Bitter	75	0	120	4	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
41	\N	SMIRNOFF	Gin, Vodkas, Rum e Bitter	35	0	60	12	4	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
43	\N	GREY GOOSE	Gin, Vodkas, Rum e Bitter	150	0	240	2	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
44	\N	CAMPARI 1L	Gin, Vodkas, Rum e Bitter	50	0	85	8	3	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
45	\N	DON LUIZ	Gin, Vodkas, Rum e Bitter	55	0	90	4	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
46	\N	MALIBU	Gin, Vodkas, Rum e Bitter	55	0	90	3	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
47	\N	GENGIBRE GARRAFA 1L	Gin, Vodkas, Rum e Bitter	30	0	60	10	3	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
48	\N	CAMPARI DOSE	Copão e Doses	4	0	20	100	20	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
49	\N	COPÃO DE RED LABEL OU CAVALO BRANCO COM RED BULL E GELO SABORIZADO	Copão e Doses	12	0	35	100	20	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
50	\N	CAVALO BRANCO DOSE	Copão e Doses	5	0	20	100	20	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
51	\N	RED LABEL DOSE	Copão e Doses	6	0	20	100	20	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
52	\N	CACHAÇAS E BATIDAS DOSE COPO PEQUENO	Copão e Doses	1.5	0	5	100	20	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
53	\N	GENGIBRE DOSE 1/2 COPO AMERICANO	Copão e Doses	2	0	7	100	20	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
54	\N	CHEETOS LUA 160G	Salgadinhos	10	0	18	20	5	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
55	\N	CHEETOS ONDA 160G	Salgadinhos	10	0	18	20	5	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
56	\N	DORITOS 120G	Salgadinhos	10	0	18	25	8	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
57	\N	FANDANGOS PRESUNTO 160G	Salgadinhos	10	0	18	15	5	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
58	\N	FANDANGOS QUEIJO 160G	Salgadinhos	10	0	18	15	5	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
59	\N	RUFFLES 115G	Salgadinhos	10	0	18	25	8	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
60	\N	BACONZITOS 86G	Salgadinhos	10	0	18	15	5	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
61	\N	BOI	Espetinhos	5	0	12	40	15	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
62	\N	FRANGO	Espetinhos	5	0	12	30	10	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
63	\N	CORAÇÃO	Espetinhos	5	0	12	30	10	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
64	\N	PÃO DE ALHO	Espetinhos	6.5	0	15	30	10	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
65	\N	MEDALHÃO	Espetinhos	6	0	14	25	8	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
66	\N	QUEIJO COALHO	Espetinhos	6	0	14	25	8	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
67	\N	CARNE DE SOL	Espetinhos	5	0	12	20	5	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
68	\N	KAFTA RECHEADA	Espetinhos	6	0	14	15	5	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
69	\N	COSTELA	Espetinhos	5	0	12	15	5	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
70	\N	PICANHA SUINA	Espetinhos	6	0	14	15	5	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
71	\N	ASA	Espetinhos	5	0	12	10	3	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
72	\N	CARNEIRO	Espetinhos	6	0	14	10	3	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
73	\N	CARVÃO 4KG	Carvão e Gelo	10	0	20	30	10	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
74	\N	GELO 4KG CUBO	Carvão e Gelo	6	0	15	50	15	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
75	\N	GELO 4KG ESCAMA	Carvão e Gelo	6	0	15	30	10	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
76	\N	GELO SABORIZADO	Carvão e Gelo	2	0	5	60	20	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
77	\N	AGUA MINERAL 500ML	Água, Refrigerantes e Energéticos	1.5	0	5	80	24	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
78	\N	AGUA CM GÁS 500ML	Água, Refrigerantes e Energéticos	1.5	0	5	40	12	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
79	\N	COCA COLA LATA 350ML	Água, Refrigerantes e Energéticos	3.5	0	8	96	24	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
80	\N	COCA COLA 2L	Água, Refrigerantes e Energéticos	7.5	0	15	30	10	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
81	\N	H2O	Água, Refrigerantes e Energéticos	4.5	0	10	36	12	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
82	\N	GUARANÁ LATA 350ML	Água, Refrigerantes e Energéticos	3.5	0	8	60	12	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
83	\N	GUARANÁ 2L	Água, Refrigerantes e Energéticos	7.5	0	15	20	6	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
84	\N	PINKMOON 600ML	Água, Refrigerantes e Energéticos	7	0	15	24	6	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
85	\N	RED BULL LT 350ML	Água, Refrigerantes e Energéticos	8	0	15	96	24	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
86	\N	CX AMSTEL GF 600ML RETORNAVEL	Engradados	0	0	240	15	5	\N	t	1	24	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
87	\N	CX HEINEKEN GF 600ML RETORNAVEL	Engradados	0	0	336	20	5	\N	t	2	24	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
88	\N	CX ORIGINAL GF 600ML RETORNAVEL	Engradados	0	0	264	15	5	\N	t	3	24	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
89	\N	CX SPATEN GF 600ML RETORNAVEL	Engradados	0	0	264	15	5	\N	t	4	24	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
90	\N	CX STELLA ARTOIS GF 600ML RETONAVEL	Engradados	0	0	312	10	3	\N	t	5	24	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
91	\N	CX AMSTEL LT 473ML	Engradados	0	0	84	15	5	\N	t	6	12	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
92	\N	CX BRAHMA CHOPP LT 473ML	Engradados	0	0	84	15	5	\N	t	7	12	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
93	\N	CX BRAHMA DM LT 350ML	Engradados	0	0	72	15	5	\N	t	8	12	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
94	\N	CX BUDWEISER LT 473ML	Engradados	0	0	84	15	5	\N	t	9	12	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
95	\N	CX CORONA LT 473ML	Engradados	0	0	108	10	3	\N	t	10	12	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
96	\N	CX HEINEKEN LT 473ML	Engradados	0	0	96	20	6	\N	t	11	12	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
97	\N	CX LAGUNITAS LT 350ML	Engradados	0	0	120	5	2	\N	t	12	12	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
98	\N	CX ORIGINAL LT 473ML	Engradados	0	0	84	15	5	\N	t	13	12	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
99	\N	CX SPATEN LT 473ML	Engradados	0	0	84	15	5	\N	t	14	12	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
100	\N	CX BUDWEISER LN 330ML	Engradados	0	0	54	10	3	\N	t	15	6	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
101	\N	CX CORONA LN 330ML	Engradados	0	0	60	10	3	\N	t	16	6	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
102	\N	CX CORONA CERO LN 330ML	Engradados	0	0	60	5	2	\N	t	17	6	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
103	\N	CX HEINEKEN LN 330ML	Engradados	0	0	60	15	4	\N	t	18	6	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
104	\N	CX SKOL BEATS SENSES/GT LONGNECK	Engradados	0	0	72	8	2	\N	t	19	6	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
105	\N	CX STELLA ARTOIS PURE GOLD LN 330ML	Engradados	0	0	60	8	2	\N	t	20	6	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
106	\N	CX WEMIX SABORES	Engradados	0	0	54	8	2	\N	t	21	6	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
107	\N	CX BRAHMA CHOPP LITRINHO 300ML	Engradados	0	0	115	6	2	\N	t	22	23	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
108	\N	CX ORIGINAL LITRINHO 300ML	Engradados	0	0	115	6	2	\N	t	23	23	2026-09-05 13:13:45.926542-03	2026-09-05 13:13:45.926542-03
42	\N	CIROC	Gin, Vodkas, Rum e Bitter	130	0	200	1	1	\N	t	\N	1	2026-09-05 13:13:44.391709-03	2026-09-05 13:22:56.140472-03
\.


--
-- Data for Name: promotion_product; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.promotion_product (promotion_id, product_id) FROM stdin;
\.


--
-- Data for Name: promotions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.promotions (id, name, description, discount_pct, start_at, end_at, is_active, created_at) FROM stdin;
\.


--
-- Data for Name: settings; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.settings (id, key, value, label, description, type, created_at, updated_at) FROM stdin;
1	store_name	Lads Beer	Nome do Estabelecimento	Nome exibido no sistema e nos tickets	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
2	store_address		Endereço	Endereço do estabelecimento	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
3	store_phone		Telefone	Telefone de contato	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
4	store_cnpj		CNPJ	CNPJ do estabelecimento	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
5	service_charge_pct	10	Taxa de Serviço (%)	Percentual sugerido no fechamento da mesa	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
6	card_fee_debit_pct	1.5	Taxa Cartão de Débito (%)	Percentual de taxa para pagamento em débito (padrão)	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
7	card_fee_credit_pct	3.5	Taxa Cartão de Crédito (%)	Percentual de taxa para pagamento em crédito (padrão)	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
8	card_machine_1_name	Maquininha 1	Nome Maquininha 1	Nome da primeira maquininha de cartão	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
9	card_machine_1_debit_fee	1.5	Taxa Débito Maquininha 1 (%)	Taxa de débito da maquininha 1	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
10	card_machine_1_credit_fee	3.5	Taxa Crédito Maquininha 1 (%)	Taxa de crédito da maquininha 1	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
11	card_machine_2_name	Maquininha 2	Nome Maquininha 2	Nome da segunda maquininha de cartão	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
12	card_machine_2_debit_fee	2.0	Taxa Débito Maquininha 2 (%)	Taxa de débito da maquininha 2	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
13	card_machine_2_credit_fee	4.0	Taxa Crédito Maquininha 2 (%)	Taxa de crédito da maquininha 2	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
14	ticket_header	Lads Beer	Cabeçalho do Ticket	Texto do cabeçalho impresso nas comandas	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
15	ticket_footer	Obrigado pela preferência!	Rodapé do Ticket	Texto do rodapé impresso nas comandas	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
16	auto_open_enabled	false	Abrir Caixa Automaticamente	Ativa abertura automática do caixa no horário configurado	boolean	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
17	auto_open_time	18:00	Horário de Abertura Automática	Horário para abrir o caixa automaticamente (HH:MM)	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
18	auto_close_enabled	false	Notificar Fechamento Automaticamente	Ativa notificação/relatório automático no horário de fechamento	boolean	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
19	auto_close_time	00:00	Horário de Fechamento Automático	Horário para enviar relatório de fechamento (HH:MM)	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
20	auto_report_email		Email para Relatório Automático	Email que recebe o relatório ao fechar o caixa	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
21	smtp_host		Servidor SMTP	Servidor SMTP para envio de emails (ex: smtp.gmail.com)	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
22	smtp_port	587	Porta SMTP	Porta do servidor SMTP	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
23	smtp_user		Usuário SMTP	Usuário/email para autenticação no SMTP	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
24	smtp_password		Senha SMTP	Senha ou app password do SMTP	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
25	smtp_from		Email Remetente	Email que aparecerá como remetente	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
26	printer_1_name	Impressora Cozinha	Nome da Impressora 1	Nome de identificação da primeira impressora térmica	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
27	printer_1_ip	192.168.1.101	IP da Impressora 1	Endereço IP da primeira impressora térmica (sugestão: 192.168.1.101)	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
28	printer_1_port	9100	Porta da Impressora 1	Porta de rede da primeira impressora térmica (padrão 9100)	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
29	printer_1_width	48	Largura da Impressora 1 (colunas)	Número de colunas de texto (32 para 58mm, 48 para 80mm)	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
30	printer_2_name	Impressora Bar	Nome da Impressora 2	Nome de identificação da segunda impressora térmica	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
31	printer_2_ip	192.168.1.102	IP da Impressora 2	Endereço IP da segunda impressora térmica (sugestão: 192.168.1.102)	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
32	printer_2_port	9100	Porta da Impressora 2	Porta de rede da segunda impressora térmica (padrão 9100)	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
33	printer_2_width	48	Largura da Impressora 2 (colunas)	Número de colunas de texto (32 para 58mm, 48 para 80mm)	number	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
34	printer_nota	1	Impressora para Nota	Qual impressora imprime a nota não fiscal (1 ou 2)	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
35	printer_cozinha	1	Impressora para Cozinha	Qual impressora imprime pedidos da cozinha (1 ou 2)	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
36	printer_bar	2	Impressora para Bar	Qual impressora imprime pedidos do bar (1 ou 2)	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
37	theme_mode	dark	Tema da Interface	Modo de exibição do sistema: claro (light) ou escuro (dark)	string	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
\.


--
-- Data for Name: stock_history; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.stock_history (id, product_id, order_id, consignment_order_id, table_id, type, quantity, note, created_at) FROM stdin;
1	42	1	\N	10	saida	1	Reserva pedido mesa 10	2026-09-05 13:17:42.323804-03
2	42	2	\N	10	saida	1	Reserva pedido mesa 10	2026-09-05 13:22:56.140472-03
\.


--
-- Data for Name: supplier_product; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.supplier_product (supplier_id, product_id) FROM stdin;
\.


--
-- Data for Name: suppliers; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.suppliers (id, name, contact, active) FROM stdin;
\.


--
-- Data for Name: tables; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.tables (id, number, name, status, is_balcao, active, created_at, updated_at) FROM stdin;
1	1	\N	vazia	f	t	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
2	2	\N	vazia	f	t	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
3	3	\N	vazia	f	t	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
4	4	\N	vazia	f	t	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
5	5	\N	vazia	f	t	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
6	6	\N	vazia	f	t	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
7	7	\N	vazia	f	t	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
8	8	\N	vazia	f	t	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
9	9	\N	vazia	f	t	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
11	0	\N	vazia	t	t	2026-09-05 13:13:44.391709-03	2026-09-05 13:13:44.391709-03
10	10	\N	vazia	f	t	2026-09-05 13:13:44.391709-03	2026-09-05 13:28:11.660898-03
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.users (id, username, password_hash, name, role, is_registered, is_active, created_at) FROM stdin;
1	sem_nome	$2b$12$nXJ1apklH3MD7aewPf6cre4SJkgboHy9J.vg/fYrE5nxCbT2wNH6O	Sem nome	garcom	f	t	2026-09-05 13:13:44.391709-03
2	gerente	$2b$12$yNqtym8Nj/.jhXldln8tWeG2DbztiYJKGIsp7j6JLMMi3/7prlwFm	Gerente	gerente	t	t	2026-09-05 13:13:44.391709-03
3	caixa	$2b$12$mmvlM2UzSZ/pp3RAj7nnNepNxZZHGGq67hz/o4Z4KpE/73SbZDIN.	Caixa	caixa	t	t	2026-09-05 13:13:44.391709-03
4	estoquista	$2b$12$eqeWxkXc2ZzQXZzjFdmXNuleN8dR4DlpNMDaHoIOrt0ygTJ866DBK	Estoquista	estoquista	t	t	2026-09-05 13:13:44.391709-03
\.


--
-- Name: cash_position_movements_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.cash_position_movements_id_seq', 1, false);


--
-- Name: cash_register_movements_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.cash_register_movements_id_seq', 1, false);


--
-- Name: cash_register_sessions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.cash_register_sessions_id_seq', 1, true);


--
-- Name: categories_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.categories_id_seq', 12, true);


--
-- Name: consignment_order_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.consignment_order_items_id_seq', 2, true);


--
-- Name: consignment_orders_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.consignment_orders_id_seq', 2, true);


--
-- Name: consignment_payments_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.consignment_payments_id_seq', 4, true);


--
-- Name: customers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.customers_id_seq', 2, true);


--
-- Name: daily_payments_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.daily_payments_id_seq', 1, false);


--
-- Name: employees_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.employees_id_seq', 2, true);


--
-- Name: expenses_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.expenses_id_seq', 1, false);


--
-- Name: notifications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.notifications_id_seq', 3, true);


--
-- Name: order_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.order_items_id_seq', 2, true);


--
-- Name: order_rounds_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.order_rounds_id_seq', 2, true);


--
-- Name: orders_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.orders_id_seq', 2, true);


--
-- Name: products_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.products_id_seq', 108, true);


--
-- Name: promotions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.promotions_id_seq', 1, false);


--
-- Name: settings_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.settings_id_seq', 37, true);


--
-- Name: stock_history_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.stock_history_id_seq', 2, true);


--
-- Name: suppliers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.suppliers_id_seq', 1, false);


--
-- Name: tables_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.tables_id_seq', 11, true);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.users_id_seq', 4, true);


--
-- Name: cash_position_movements cash_position_movements_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_position_movements
    ADD CONSTRAINT cash_position_movements_pkey PRIMARY KEY (id);


--
-- Name: cash_register_movements cash_register_movements_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_register_movements
    ADD CONSTRAINT cash_register_movements_pkey PRIMARY KEY (id);


--
-- Name: cash_register_sessions cash_register_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_register_sessions
    ADD CONSTRAINT cash_register_sessions_pkey PRIMARY KEY (id);


--
-- Name: categories categories_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.categories
    ADD CONSTRAINT categories_name_key UNIQUE (name);


--
-- Name: categories categories_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.categories
    ADD CONSTRAINT categories_pkey PRIMARY KEY (id);


--
-- Name: consignment_order_items consignment_order_items_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_order_items
    ADD CONSTRAINT consignment_order_items_pkey PRIMARY KEY (id);


--
-- Name: consignment_orders consignment_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_orders
    ADD CONSTRAINT consignment_orders_pkey PRIMARY KEY (id);


--
-- Name: consignment_payments consignment_payments_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_payments
    ADD CONSTRAINT consignment_payments_pkey PRIMARY KEY (id);


--
-- Name: customers customers_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (id);


--
-- Name: daily_payments daily_payments_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_payments
    ADD CONSTRAINT daily_payments_pkey PRIMARY KEY (id);


--
-- Name: employees employees_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_pkey PRIMARY KEY (id);


--
-- Name: expenses expenses_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.expenses
    ADD CONSTRAINT expenses_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: order_items order_items_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_pkey PRIMARY KEY (id);


--
-- Name: order_rounds order_rounds_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.order_rounds
    ADD CONSTRAINT order_rounds_pkey PRIMARY KEY (id);


--
-- Name: orders orders_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);


--
-- Name: products products_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_code_key UNIQUE (code);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);


--
-- Name: promotion_product promotion_product_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.promotion_product
    ADD CONSTRAINT promotion_product_pkey PRIMARY KEY (promotion_id, product_id);


--
-- Name: promotions promotions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_pkey PRIMARY KEY (id);


--
-- Name: settings settings_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.settings
    ADD CONSTRAINT settings_key_key UNIQUE (key);


--
-- Name: settings settings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.settings
    ADD CONSTRAINT settings_pkey PRIMARY KEY (id);


--
-- Name: stock_history stock_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_history
    ADD CONSTRAINT stock_history_pkey PRIMARY KEY (id);


--
-- Name: supplier_product supplier_product_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.supplier_product
    ADD CONSTRAINT supplier_product_pkey PRIMARY KEY (supplier_id, product_id);


--
-- Name: suppliers suppliers_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.suppliers
    ADD CONSTRAINT suppliers_pkey PRIMARY KEY (id);


--
-- Name: tables tables_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tables
    ADD CONSTRAINT tables_number_key UNIQUE (number);


--
-- Name: tables tables_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tables
    ADD CONSTRAINT tables_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: cash_position_movements cash_position_movements_created_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_position_movements
    ADD CONSTRAINT cash_position_movements_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES public.users(id);


--
-- Name: cash_position_movements cash_position_movements_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_position_movements
    ADD CONSTRAINT cash_position_movements_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.cash_register_sessions(id);


--
-- Name: cash_register_movements cash_register_movements_created_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_register_movements
    ADD CONSTRAINT cash_register_movements_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES public.users(id);


--
-- Name: cash_register_movements cash_register_movements_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_register_movements
    ADD CONSTRAINT cash_register_movements_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.cash_register_sessions(id);


--
-- Name: cash_register_sessions cash_register_sessions_closed_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_register_sessions
    ADD CONSTRAINT cash_register_sessions_closed_by_id_fkey FOREIGN KEY (closed_by_id) REFERENCES public.users(id);


--
-- Name: cash_register_sessions cash_register_sessions_opened_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cash_register_sessions
    ADD CONSTRAINT cash_register_sessions_opened_by_id_fkey FOREIGN KEY (opened_by_id) REFERENCES public.users(id);


--
-- Name: consignment_order_items consignment_order_items_consignment_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_order_items
    ADD CONSTRAINT consignment_order_items_consignment_order_id_fkey FOREIGN KEY (consignment_order_id) REFERENCES public.consignment_orders(id);


--
-- Name: consignment_order_items consignment_order_items_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_order_items
    ADD CONSTRAINT consignment_order_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: consignment_orders consignment_orders_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_orders
    ADD CONSTRAINT consignment_orders_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id);


--
-- Name: consignment_orders consignment_orders_source_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_orders
    ADD CONSTRAINT consignment_orders_source_order_id_fkey FOREIGN KEY (source_order_id) REFERENCES public.orders(id);


--
-- Name: consignment_orders consignment_orders_waiter_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_orders
    ADD CONSTRAINT consignment_orders_waiter_id_fkey FOREIGN KEY (waiter_id) REFERENCES public.users(id);


--
-- Name: consignment_payments consignment_payments_consignment_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_payments
    ADD CONSTRAINT consignment_payments_consignment_order_id_fkey FOREIGN KEY (consignment_order_id) REFERENCES public.consignment_orders(id);


--
-- Name: consignment_payments consignment_payments_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.consignment_payments
    ADD CONSTRAINT consignment_payments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: daily_payments daily_payments_employee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_payments
    ADD CONSTRAINT daily_payments_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES public.employees(id);


--
-- Name: daily_payments daily_payments_registered_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_payments
    ADD CONSTRAINT daily_payments_registered_by_id_fkey FOREIGN KEY (registered_by_id) REFERENCES public.users(id);


--
-- Name: employees employees_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: expenses expenses_created_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.expenses
    ADD CONSTRAINT expenses_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES public.users(id);


--
-- Name: order_items order_items_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id);


--
-- Name: order_items order_items_order_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_order_round_id_fkey FOREIGN KEY (order_round_id) REFERENCES public.order_rounds(id);


--
-- Name: order_items order_items_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: order_rounds order_rounds_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.order_rounds
    ADD CONSTRAINT order_rounds_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id);


--
-- Name: orders orders_closed_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_closed_by_id_fkey FOREIGN KEY (closed_by_id) REFERENCES public.users(id);


--
-- Name: orders orders_closed_waiter_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_closed_waiter_id_fkey FOREIGN KEY (closed_waiter_id) REFERENCES public.employees(id);


--
-- Name: orders orders_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id);


--
-- Name: orders orders_table_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_table_id_fkey FOREIGN KEY (table_id) REFERENCES public.tables(id);


--
-- Name: orders orders_waiter_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_waiter_id_fkey FOREIGN KEY (waiter_id) REFERENCES public.users(id);


--
-- Name: products products_pack_unit_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pack_unit_product_id_fkey FOREIGN KEY (pack_unit_product_id) REFERENCES public.products(id);


--
-- Name: promotion_product promotion_product_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.promotion_product
    ADD CONSTRAINT promotion_product_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: promotion_product promotion_product_promotion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.promotion_product
    ADD CONSTRAINT promotion_product_promotion_id_fkey FOREIGN KEY (promotion_id) REFERENCES public.promotions(id);


--
-- Name: stock_history stock_history_consignment_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_history
    ADD CONSTRAINT stock_history_consignment_order_id_fkey FOREIGN KEY (consignment_order_id) REFERENCES public.consignment_orders(id);


--
-- Name: stock_history stock_history_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_history
    ADD CONSTRAINT stock_history_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id);


--
-- Name: stock_history stock_history_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_history
    ADD CONSTRAINT stock_history_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: stock_history stock_history_table_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stock_history
    ADD CONSTRAINT stock_history_table_id_fkey FOREIGN KEY (table_id) REFERENCES public.tables(id);


--
-- Name: supplier_product supplier_product_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.supplier_product
    ADD CONSTRAINT supplier_product_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: supplier_product supplier_product_supplier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.supplier_product
    ADD CONSTRAINT supplier_product_supplier_id_fkey FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id);


--
-- PostgreSQL database dump complete
--

\unrestrict IPi4cBqgaZ4g7eRYdbvdIoMKVknma5UciJ4phfJJG225rYVAqRrPd51xqP2wvg8

