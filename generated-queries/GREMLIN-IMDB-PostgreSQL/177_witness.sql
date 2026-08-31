SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((movie_companies CROSS JOIN (title CROSS JOIN person_info)) CROSS JOIN movie_info) CROSS JOIN info_type) CROSS JOIN kind_type) CROSS JOIN movie_keyword) CROSS JOIN keyword) CROSS JOIN company_name
WHERE company_name.name_pcode_sf = ''
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND title.kind_id = kind_type.id;
