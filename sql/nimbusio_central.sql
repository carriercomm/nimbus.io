/****
 * schema for centralized nimbus.io database
 ****/

begin;

drop schema if exists nimbusio_central cascade;
create schema nimbusio_central;
set search_path to nimbusio_central, public;

/* just a mostly informational table to describe the details of the whole cluster */
create table "cluster" (
    id serial primary key,
    name varchar(255) unique not null,
    node_count int4 not null default 10,
    replication_level int4 not null default 3,
    creation_time timestamp default 'now'
);

create table node (
    id serial primary key,
    cluster_id int4 not null,
    node_number_in_cluster int4 not null,
    name varchar(255) unique not null,
    hostname varchar(255) not null,
    offline bool not null default false,
    creation_time timestamp default 'now'
);

create sequence customer_id_seq;
create table customer (
    id int4 unique not null default nextval('nimbusio_central.customer_id_seq'),
    creation_time timestamp not null default now(),
    username varchar(60) unique not null
);

/* get customer row for username */
create index customer_usernname_idx on nimbusio_central.customer("username");

create sequence customer_key_id_seq;
create table customer_key(
   id int4 unique not null default nextval('nimbusio_central.customer_key_id_seq'),  
   customer_id int4 not null references nimbusio_central.customer(id),
   key text not null,
   unique (customer_id, key)
);

create index customer_key_customer_idx on nimbusio_central.customer_key("customer_id");

create sequence collection_id_seq;
create table collection (
    id int4 unique not null default nextval('nimbusio_central.collection_id_seq'),
    name varchar(1024) unique not null,
    customer_id int4 not null references nimbusio_central.customer(id),
    creation_time timestamp not null default 'now'
);

/* get collection_row for collection name */
create index collection_name_idx on nimbusio_central.collection("name");

/* get all collection names for customer_id */
create index collection_customer_id_name_idx on nimbusio_central.collection("customer_id", "name");

create table space_accounting(
   collecton_id int4 not null references nimbusio_central.collection(id),
   timestamp timestamp not null,
   bytes_added int8 not null default 0,
   bytes_removed int8 not null default 0,
   bytes_retrieved int8 not null default 0
);

create sequence audit_result_id_sequence;
create table audit_result(
   diyapi_audit_result_id int4 not null primary key default nextval('nimbusio_central.audit_result_id_sequence'),
   collection_id int4 not null references nimbusio_central.collection(id),
   state text,
   audit_scheduled timestamp default now(),
   audit_started timestamp,
   audit_finished timestamp,
   reconstruct_scheduled timestamp,
   reconstruct_started timestamp,
   reconstruct_finished timestamp
);

create index audit_result_collection_id on nimbusio_central.audit_result (collection_id);

grant all privileges on schema nimbusio_central to pandora;
grant all privileges on all tables in schema nimbusio_central to pandora;
grant all privileges on all sequences in schema nimbusio_central to pandora;

/*rollback;*/
commit;

