SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((((((movie_companies CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN movie_link) CROSS JOIN aka_title) CROSS JOIN company_type) CROSS JOIN cast_info) CROSS JOIN role_type) CROSS JOIN movie_keyword) CROSS JOIN name) CROSS JOIN keyword) CROSS JOIN person_info) CROSS JOIN char_name
WHERE aka_title.episode_nr = 1
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
