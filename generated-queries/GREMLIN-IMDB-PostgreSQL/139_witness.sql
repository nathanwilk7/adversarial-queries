SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((((movie_companies CROSS JOIN (title CROSS JOIN movie_link)) CROSS JOIN aka_title) CROSS JOIN info_type) CROSS JOIN name) CROSS JOIN person_info) CROSS JOIN movie_keyword) CROSS JOIN movie_info) CROSS JOIN keyword) CROSS JOIN company_type
WHERE aka_title.season_nr = 63
  AND aka_title.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
