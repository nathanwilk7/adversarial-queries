SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((movie_companies CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN info_type) CROSS JOIN aka_title) CROSS JOIN company_name) CROSS JOIN name) CROSS JOIN person_info) CROSS JOIN movie_info) CROSS JOIN movie_keyword
WHERE aka_title.season_nr = 63
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
