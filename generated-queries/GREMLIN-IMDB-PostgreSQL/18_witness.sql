SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((movie_companies CROSS JOIN (title CROSS JOIN aka_name)) CROSS JOIN info_type) CROSS JOIN movie_info) CROSS JOIN name) CROSS JOIN company_name) CROSS JOIN person_info
WHERE company_name.name_pcode_sf = ''
  AND aka_name.person_id = name.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
