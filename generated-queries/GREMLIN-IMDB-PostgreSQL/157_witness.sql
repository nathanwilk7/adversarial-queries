SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((title CROSS JOIN person_info) CROSS JOIN movie_companies) CROSS JOIN movie_info) CROSS JOIN info_type) CROSS JOIN aka_title) CROSS JOIN company_name) CROSS JOIN kind_type) CROSS JOIN name
WHERE company_name.name_pcode_sf = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
