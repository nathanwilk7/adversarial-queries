SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((((title CROSS JOIN aka_title) CROSS JOIN movie_companies) CROSS JOIN info_type) CROSS JOIN keyword) CROSS JOIN kind_type) CROSS JOIN movie_info) CROSS JOIN movie_keyword) CROSS JOIN company_type) CROSS JOIN person_info
WHERE aka_title.season_nr = 63
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND title.kind_id = kind_type.id;
