SELECT count(*)
FROM aka_title, cast_info, info_type, kind_type, movie_companies, movie_info, movie_keyword, movie_link, person_info, role_type, title
WHERE aka_title.title = 'Anonima ricatti'
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND title.kind_id = kind_type.id;
