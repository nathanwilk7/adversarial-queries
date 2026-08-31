SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((movie_companies CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN name) CROSS JOIN company_name) CROSS JOIN movie_info) CROSS JOIN person_info) CROSS JOIN info_type) CROSS JOIN aka_name
WHERE company_name.name_pcode_sf = ''
  AND aka_name.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
