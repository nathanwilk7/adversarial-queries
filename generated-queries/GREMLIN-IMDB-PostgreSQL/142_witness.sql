SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((movie_keyword CROSS JOIN aka_title) CROSS JOIN company_type) CROSS JOIN info_type) CROSS JOIN movie_companies) CROSS JOIN movie_info) CROSS JOIN person_info) CROSS JOIN title
WHERE aka_title.season_nr = 63
  AND aka_title.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND person_info.info_type_id = info_type.id;
