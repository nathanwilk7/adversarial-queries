SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((((((title CROSS JOIN movie_companies) CROSS JOIN movie_link) CROSS JOIN company_type) CROSS JOIN aka_title) CROSS JOIN movie_info) CROSS JOIN link_type) CROSS JOIN complete_cast) CROSS JOIN cast_info) CROSS JOIN name) CROSS JOIN role_type) CROSS JOIN person_info
WHERE aka_title.episode_nr = 1
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
