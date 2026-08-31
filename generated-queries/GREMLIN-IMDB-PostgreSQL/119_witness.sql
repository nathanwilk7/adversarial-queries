SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((((movie_companies CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN aka_title) CROSS JOIN company_name) CROSS JOIN kind_type) CROSS JOIN role_type) CROSS JOIN movie_keyword) CROSS JOIN cast_info) CROSS JOIN movie_info) CROSS JOIN keyword
WHERE aka_title.season_nr = 1
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND title.kind_id = kind_type.id;
