SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((((((movie_companies CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN cast_info) CROSS JOIN aka_title) CROSS JOIN keyword) CROSS JOIN company_type) CROSS JOIN movie_link) CROSS JOIN movie_keyword) CROSS JOIN movie_info) CROSS JOIN person_info) CROSS JOIN role_type) CROSS JOIN info_type
WHERE aka_title.season_nr = 63
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id;
